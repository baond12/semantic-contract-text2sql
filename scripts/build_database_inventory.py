import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path


def read_text_if_exists(path):
    path = Path(path)
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def load_json_if_exists(path, default):
    path = Path(path)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def save_json(data, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fetch_all_dicts(connection, sql, params=()):
    connection.row_factory = sqlite3.Row
    rows = connection.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def list_user_tables(connection):
    rows = fetch_all_dicts(
        connection,
        """
        SELECT name
        FROM sqlite_master
        WHERE type='table'
          AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """,
    )
    return [row["name"] for row in rows]


def table_row_count(connection, table_name):
    row = connection.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()
    return int(row[0])


def table_columns(connection, table_name):
    rows = fetch_all_dicts(connection, f'PRAGMA table_info("{table_name}")')
    columns = []
    for row in rows:
        columns.append(
            {
                "table": table_name,
                "column": row["name"],
                "column_id": f"{table_name}.{row['name']}",
                "data_type": row["type"],
                "not_null": bool(row["notnull"]),
                "default_value": row["dflt_value"],
                "is_primary_key": bool(row["pk"]),
                "primary_key_position": row["pk"],
            }
        )
    return columns


def table_foreign_keys(connection, table_name):
    rows = fetch_all_dicts(connection, f'PRAGMA foreign_key_list("{table_name}")')
    relationships = []
    for row in rows:
        relationships.append(
            {
                "relationship_id": f"{table_name}.{row['from']}->{row['table']}.{row['to']}",
                "source_table": table_name,
                "source_column": row["from"],
                "target_table": row["table"],
                "target_column": row["to"],
                "on_update": row["on_update"],
                "on_delete": row["on_delete"],
                "match": row["match"],
            }
        )
    return relationships


def table_indexes(connection, table_name):
    rows = fetch_all_dicts(connection, f'PRAGMA index_list("{table_name}")')
    indexes = []
    for row in rows:
        index_name = row["name"]
        index_columns = fetch_all_dicts(connection, f'PRAGMA index_info("{index_name}")')
        indexes.append(
            {
                "table": table_name,
                "index_name": index_name,
                "is_unique": bool(row["unique"]),
                "origin": row["origin"],
                "columns": [item["name"] for item in index_columns],
            }
        )
    return indexes


def sample_column_values(connection, table_name, column_name, limit):
    sql = f'''
    SELECT "{column_name}" AS value, COUNT(*) AS frequency
    FROM "{table_name}"
    WHERE "{column_name}" IS NOT NULL
    GROUP BY "{column_name}"
    ORDER BY frequency DESC, "{column_name}"
    LIMIT ?
    '''
    rows = fetch_all_dicts(connection, sql, (limit,))
    return rows


def infer_table_role(table_name, row_count, relationships):
    outgoing_count = sum(1 for item in relationships if item["source_table"] == table_name)
    incoming_count = sum(1 for item in relationships if item["target_table"] == table_name)

    if incoming_count > 0 and outgoing_count == 0 and row_count <= 100:
        return "reference"
    if incoming_count > 0 and outgoing_count > 0:
        return "entity_or_transaction"
    if incoming_count == 0 and outgoing_count > 0:
        return "fact_or_child_entity"
    return "standalone_or_reference"


def infer_column_role(column, relationships):
    column_id = column["column_id"]
    is_fk = any(
        column["table"] == item["source_table"] and column["column"] == item["source_column"]
        for item in relationships
    )

    if column["is_primary_key"]:
        return "identifier"
    if is_fk:
        return "foreign_key"
    if column["column"] in ["name", "product_name", "brand_name", "category_name", "channel_name", "store_name"]:
        return "display_name"
    if column["column"].endswith("_at") or column["column"].endswith("_date"):
        return "time"
    if any(token in column["column"] for token in ["amount", "price", "qty", "count", "fee", "discount"]):
        return "measure_or_numeric"
    if column["column"].endswith("_status") or column["column"] == "status":
        return "status"
    return "attribute"


def build_benchmark_summary(benchmark_spec):
    groups = Counter()
    difficulties = Counter()
    actions = Counter()
    methods = Counter()

    for item in benchmark_spec:
        groups[item.get("group", "")] += 1
        difficulties[item.get("difficulty", "")] += 1
        actions[item.get("expected_action", "")] += 1
        methods[item.get("method", "")] += 1

    return {
        "case_count": len(benchmark_spec),
        "group_count": len([key for key in groups if key]),
        "groups": dict(sorted(groups.items())),
        "difficulties": dict(sorted(difficulties.items())),
        "expected_actions": dict(sorted(actions.items())),
        "methods": dict(sorted(methods.items())),
    }


def build_database_inventory(database_id, sqlite_path, schema_path, benchmark_spec_path, output_dir, sample_limit):
    sqlite_path = Path(sqlite_path)
    output_dir = Path(output_dir)

    connection = sqlite3.connect(sqlite_path)
    table_names = list_user_tables(connection)

    relationships = []
    for table_name in table_names:
        relationships.extend(table_foreign_keys(connection, table_name))

    tables = []
    columns = []
    sample_values = []
    indexes = []

    for table_name in table_names:
        row_count = table_row_count(connection, table_name)
        table_columns_list = table_columns(connection, table_name)
        table_indexes_list = table_indexes(connection, table_name)

        tables.append(
            {
                "table": table_name,
                "row_count": row_count,
                "column_count": len(table_columns_list),
                "table_role_guess": infer_table_role(table_name, row_count, relationships),
                "primary_key_columns": [
                    column["column"]
                    for column in table_columns_list
                    if column["is_primary_key"]
                ],
            }
        )

        for column in table_columns_list:
            column["column_role_guess"] = infer_column_role(column, relationships)
            columns.append(column)
            sample_values.append(
                {
                    "table": table_name,
                    "column": column["column"],
                    "column_id": column["column_id"],
                    "sample_values": sample_column_values(
                        connection=connection,
                        table_name=table_name,
                        column_name=column["column"],
                        limit=sample_limit,
                    ),
                }
            )

        indexes.extend(table_indexes_list)

    benchmark_spec = load_json_if_exists(benchmark_spec_path, [])
    schema_sql = read_text_if_exists(schema_path)

    overview = {
        "database_id": database_id,
        "sqlite_path": str(sqlite_path),
        "schema_path": str(schema_path),
        "benchmark_spec_path": str(benchmark_spec_path),
        "table_count": len(tables),
        "column_count": len(columns),
        "relationship_count": len(relationships),
        "index_count": len(indexes),
        "total_row_count": sum(table["row_count"] for table in tables),
        "benchmark_summary": build_benchmark_summary(benchmark_spec),
    }

    save_json(tables, output_dir / "tables.json")
    save_json(columns, output_dir / "columns.json")
    save_json(relationships, output_dir / "relationships.json")
    save_json(indexes, output_dir / "indexes.json")
    save_json(sample_values, output_dir / "sample_values.json")
    save_json(overview, output_dir / "database_overview.json")
    save_json(benchmark_spec, output_dir / "benchmark_spec_snapshot.json")
    (output_dir / "schema_snapshot.sql").write_text(schema_sql, encoding="utf-8")

    source_manifest = {
        "database_id": database_id,
        "source_files": {
            "sqlite_path": str(sqlite_path),
            "schema_path": str(schema_path),
            "benchmark_spec_path": str(benchmark_spec_path),
        },
        "output_files": {
            "tables": str(output_dir / "tables.json"),
            "columns": str(output_dir / "columns.json"),
            "relationships": str(output_dir / "relationships.json"),
            "indexes": str(output_dir / "indexes.json"),
            "sample_values": str(output_dir / "sample_values.json"),
            "database_overview": str(output_dir / "database_overview.json"),
            "benchmark_spec_snapshot": str(output_dir / "benchmark_spec_snapshot.json"),
            "schema_snapshot": str(output_dir / "schema_snapshot.sql"),
        },
    }
    save_json(source_manifest, output_dir / "source_files_manifest.json")

    connection.close()
    return overview


def build_parser():
    parser = argparse.ArgumentParser(
        description="Build database inventory from SQLite/schema/benchmark spec."
    )
    parser.add_argument("--database-id", required=True)
    parser.add_argument("--sqlite-path", required=True)
    parser.add_argument("--schema-path", required=True)
    parser.add_argument("--benchmark-spec-path", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--sample-limit", type=int, default=8)
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    overview = build_database_inventory(
        database_id=args.database_id,
        sqlite_path=args.sqlite_path,
        schema_path=args.schema_path,
        benchmark_spec_path=args.benchmark_spec_path,
        output_dir=args.output_dir,
        sample_limit=args.sample_limit,
    )

    print(json.dumps(overview, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

