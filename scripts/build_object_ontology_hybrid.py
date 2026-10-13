import argparse
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path


DEFAULT_CONFIG_PATH = Path("/home/baond12/projects/Text2Sql_Q3/2026-09-22/llm_config.yaml")
COMPANY_PROXY_URL = "http://proxy.hcm.fpt.vn:80"


def configure_proxy(proxy_mode):
    if proxy_mode == "company":
        os.environ["http_proxy"] = COMPANY_PROXY_URL
        os.environ["https_proxy"] = COMPANY_PROXY_URL
        os.environ["HTTP_PROXY"] = COMPANY_PROXY_URL
        os.environ["HTTPS_PROXY"] = COMPANY_PROXY_URL
        os.environ["no_proxy"] = ""
        os.environ["NO_PROXY"] = ""
        return

    if proxy_mode == "none":
        for key in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "no_proxy", "NO_PROXY"]:
            os.environ.pop(key, None)


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_json(data, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def snake_to_pascal(name):
    special = {
        "sku": "SKU",
        "gmv": "GMV",
        "aov": "AOV",
    }
    parts = [part for part in re.split(r"[_\s]+", name) if part]
    return "".join(special.get(part.lower(), part[:1].upper() + part[1:]) for part in parts)


def singularize(name):
    if name.endswith("ies"):
        return name[:-3] + "y"
    if name.endswith("ses"):
        return name[:-2]
    if name.endswith("s") and not name.endswith("ss"):
        return name[:-1]
    return name


def table_to_class_id(table_name):
    return snake_to_pascal(singularize(table_name))


def column_to_property_name(column_name):
    parts = [part for part in column_name.split("_") if part]
    if not parts:
        return column_name
    return parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])


def infer_property_type(column):
    role = column.get("column_role_guess", "")
    if role == "foreign_key":
        return "object_key"
    return "datatype_property"


def infer_class_role(table):
    role = table.get("table_role_guess", "")
    if role == "reference":
        return "reference_class"
    if role == "fact_or_child_entity":
        return "fact_or_event_class"
    if role == "entity_or_transaction":
        return "entity_or_transaction_class"
    return "entity_class"


def build_table_lookup(tables):
    return {item["table"]: item for item in tables}


def build_column_lookup(columns):
    return defaultdict(list, {
        table: [column for column in columns if column["table"] == table]
        for table in sorted({column["table"] for column in columns})
    })


def build_sample_lookup(sample_values):
    return {
        item["column_id"]: item.get("sample_values", [])
        for item in sample_values
    }


def compact_table_context(tables, columns_by_table, sample_lookup, relationships):
    incoming = defaultdict(list)
    outgoing = defaultdict(list)
    for rel in relationships:
        outgoing[rel["source_table"]].append(rel)
        incoming[rel["target_table"]].append(rel)

    cards = []
    for table in tables:
        table_name = table["table"]
        column_cards = []
        for column in columns_by_table[table_name]:
            samples = sample_lookup.get(column["column_id"], [])[:4]
            column_cards.append(
                {
                    "column": column["column"],
                    "data_type": column["data_type"],
                    "role_guess": column.get("column_role_guess"),
                    "sample_values": [item["value"] for item in samples],
                }
            )

        cards.append(
            {
                "table": table_name,
                "row_count": table["row_count"],
                "table_role_guess": table.get("table_role_guess"),
                "primary_key_columns": table.get("primary_key_columns", []),
                "columns": column_cards,
                "outgoing_relationships": outgoing[table_name],
                "incoming_relationships": incoming[table_name],
            }
        )
    return cards


def benchmark_context(benchmark_spec):
    groups = defaultdict(list)
    methods = defaultdict(list)
    actions = Counter()
    for item in benchmark_spec:
        groups[item.get("group", "")].append(item)
        methods[item.get("method", "")].append(item)
        actions[item.get("expected_action", "")] += 1

    group_cards = []
    for group, items in sorted(groups.items()):
        group_cards.append(
            {
                "group": group,
                "case_count": len(items),
                "sample_questions": [item.get("question", "") for item in items[:5]],
                "methods": sorted({item.get("method", "") for item in items if item.get("method")}),
                "expected_actions": dict(Counter(item.get("expected_action", "") for item in items)),
            }
        )

    method_cards = []
    for method, items in sorted(methods.items()):
        method_cards.append(
            {
                "method": method,
                "case_count": len(items),
                "groups": sorted({item.get("group", "") for item in items if item.get("group")}),
                "sample_questions": [item.get("question", "") for item in items[:4]],
                "required_semantics": sorted({item.get("required", "") for item in items if item.get("required")})[:8],
                "forbidden_semantics": sorted({item.get("forbidden", "") for item in items if item.get("forbidden")})[:8],
            }
        )

    return {
        "group_cards": group_cards,
        "method_cards": method_cards,
        "expected_actions": dict(actions),
    }


OBJECT_ONTOLOGY_LLM_CONTRACT = {
    "class_enrichments": [
        {
            "table": "source table",
            "class_id": "PascalCase class id",
            "class_name": "human readable class name",
            "business_description": "short business meaning",
            "business_domain": "Catalog | Orders | Revenue | Inventory | Customers | Fulfillment | Support | Other",
            "class_role": "reference | entity | transaction | fact | bridge | event",
            "default_display_property": "property name or null",
            "confidence": 0.0,
        }
    ],
    "method_enrichments": [
        {
            "method_id": "stable method id",
            "business_domain": "business domain",
            "description": "what this method answers",
            "target_classes": ["ClassId"],
            "operation_intent": "count | list | lookup | aggregate | rank | compare | clarify | unsupported | refuse",
            "required_parameters": [],
            "optional_parameters": [],
            "required_semantics": [],
            "forbidden_semantics": [],
            "confidence": 0.0,
        }
    ],
    "unsupported_scope_candidates": [
        {
            "scope_id": "snake_case_id",
            "description": "unsupported or refuse condition",
            "expected_action": "CLARIFY | REFUSE | UNSUPPORTED",
            "signals": [],
            "reason": "why system should not execute SQL",
            "confidence": 0.0,
        }
    ],
}


CLASS_ENRICHMENT_CONTRACT = {
    "class_enrichments": [
        {
            "table": "source table",
            "class_id": "PascalCase class id",
            "class_name": "human readable class name",
            "business_description": "short business meaning",
            "business_domain": "Catalog | Orders | Revenue | Inventory | Customers | Fulfillment | Support | Other",
            "class_role": "reference | entity | transaction | fact | bridge | event",
            "default_display_property": "property name or null",
            "confidence": 0.0,
        }
    ]
}


METHOD_ENRICHMENT_CONTRACT = {
    "method_enrichments": [
        {
            "method_id": "stable method id from input",
            "business_domain": "business domain",
            "description": "what this method answers",
            "target_classes": ["ClassId"],
            "operation_intent": "count | list | lookup | aggregate | rank | compare | clarify | unsupported | refuse",
            "required_parameters": [],
            "optional_parameters": [],
            "required_semantics": [],
            "forbidden_semantics": [],
            "confidence": 0.0,
        }
    ]
}


UNSUPPORTED_SCOPE_CONTRACT = {
    "unsupported_scope_candidates": [
        {
            "scope_id": "same scope id from input",
            "description": "unsupported, clarify, or refuse condition",
            "expected_action": "CLARIFY | REFUSE | UNSUPPORTED",
            "signals": [],
            "reason": "why system should not execute SQL directly",
            "confidence": 0.0,
        }
    ]
}


def call_llm(system_prompt, user_prompt, config_path):
    import yaml
    from openai import OpenAI

    config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    dc5 = config["dc5"]
    client = OpenAI(api_key=dc5["api_key"], base_url=dc5["base_url"], timeout=120)
    response = client.chat.completions.create(
        model=dc5["model"],
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0,
        max_tokens=5000,
        extra_body={
            "chat_template_kwargs": {
                "enable_thinking": False,
            }
        },
    )
    return response.choices[0].message.content


def extract_json_object(text):
    start = text.find("{")
    end = text.rfind("}") + 1
    if start < 0 or end <= start:
        raise ValueError("LLM output does not contain JSON object.")
    return json.loads(text[start:end])


def call_json_llm(task_name, contract, context, config_path):
    system_prompt = """
Bạn là ontology architect cho Text2SQL trong môi trường industry.

Nhiệm vụ:
- Đọc context được cung cấp.
- Bổ sung ý nghĩa nghiệp vụ cho object ontology theo đúng task.
- Không sinh SQL.
- Không tự tạo bảng/cột không có trong input.
- Trả về JSON đúng contract.
- Viết ngắn gọn, không giải thích ngoài JSON.
"""

    user_prompt = f"""
TASK:
{task_name}

DATABASE_ID:
{context["database_id"]}

CONTRACT:
{json.dumps(contract, ensure_ascii=False, indent=2)}

CONTEXT:
{json.dumps(context, ensure_ascii=False, indent=2)}

Return only JSON.
"""
    raw_output = call_llm(system_prompt, user_prompt, config_path)
    parsed = extract_json_object(raw_output)
    return parsed, raw_output, system_prompt, user_prompt


def enrich_object_ontology_with_llm(database_id, table_cards, benchmark_cards, unsupported_candidates, config_path):
    class_context = {
        "database_id": database_id,
        "table_cards": table_cards,
    }
    method_context = {
        "database_id": database_id,
        "method_cards": benchmark_cards["method_cards"],
        "group_cards": benchmark_cards["group_cards"],
    }
    unsupported_context = {
        "database_id": database_id,
        "unsupported_scope_candidates": unsupported_candidates,
    }

    class_output, class_raw, class_system, class_user = call_json_llm(
        task_name="Enrich database tables into business object classes.",
        contract=CLASS_ENRICHMENT_CONTRACT,
        context=class_context,
        config_path=config_path,
    )
    method_output, method_raw, method_system, method_user = call_json_llm(
        task_name="Enrich benchmark method candidates into ontology method candidates.",
        contract=METHOD_ENRICHMENT_CONTRACT,
        context=method_context,
        config_path=config_path,
    )
    unsupported_output, unsupported_raw, unsupported_system, unsupported_user = call_json_llm(
        task_name="Enrich clarify/refuse/unsupported cases into unsupported scope policy candidates.",
        contract=UNSUPPORTED_SCOPE_CONTRACT,
        context=unsupported_context,
        config_path=config_path,
    )

    parsed = {
        "class_enrichments": class_output.get("class_enrichments", []),
        "method_enrichments": method_output.get("method_enrichments", []),
        "unsupported_scope_candidates": unsupported_output.get("unsupported_scope_candidates", []),
    }
    raw_trace = {
        "class_enrichment": {
            "raw_output": class_raw,
            "parsed_output": class_output,
            "system_prompt": class_system,
            "user_prompt": class_user,
        },
        "method_enrichment": {
            "raw_output": method_raw,
            "parsed_output": method_output,
            "system_prompt": method_system,
            "user_prompt": method_user,
        },
        "unsupported_scope_enrichment": {
            "raw_output": unsupported_raw,
            "parsed_output": unsupported_output,
            "system_prompt": unsupported_system,
            "user_prompt": unsupported_user,
        },
    }
    return parsed, raw_trace


def deterministic_classes(database_id, tables):
    classes = []
    for table in tables:
        class_id = table_to_class_id(table["table"])
        classes.append(
            {
                "class_id": class_id,
                "class_name": class_id,
                "source_table": table["table"],
                "class_role": infer_class_role(table),
                "business_domain": "unknown",
                "description": f"Object class mapped from table {table['table']}.",
                "default_display_property": None,
                "row_count": table["row_count"],
                "column_count": table["column_count"],
                "primary_key_columns": table.get("primary_key_columns", []),
                "construction_source": "deterministic_inventory",
            }
        )
    return classes


def deterministic_properties(columns):
    properties = []
    for column in columns:
        class_id = table_to_class_id(column["table"])
        property_name = column_to_property_name(column["column"])
        properties.append(
            {
                "property_id": f"{class_id}.{property_name}",
                "class_id": class_id,
                "property_name": property_name,
                "property_type": infer_property_type(column),
                "source_column": column["column_id"],
                "data_type": column["data_type"],
                "is_identifier": column.get("column_role_guess") == "identifier",
                "is_object_key": column.get("column_role_guess") == "foreign_key",
                "role_guess": column.get("column_role_guess"),
                "description": f"Property mapped from column {column['column_id']}.",
                "construction_source": "deterministic_inventory",
            }
        )
    return properties


def relation_name(source_table, target_table):
    source_class = table_to_class_id(source_table)
    target_class = table_to_class_id(target_table)
    return f"{source_class}.relatesTo{target_class}"


def deterministic_relations(relationships):
    relations = []
    for rel in relationships:
        source_class = table_to_class_id(rel["source_table"])
        target_class = table_to_class_id(rel["target_table"])
        source_prop = column_to_property_name(rel["source_column"])
        target_prop = column_to_property_name(rel["target_column"])
        relations.append(
            {
                "relation_id": relation_name(rel["source_table"], rel["target_table"]),
                "relation_name": f"relatesTo{target_class}",
                "source_class": source_class,
                "target_class": target_class,
                "cardinality": "N:1",
                "source_property": f"{source_class}.{source_prop}",
                "target_property": f"{target_class}.{target_prop}",
                "database_mapping": {
                    "left": f"{rel['source_table']}.{rel['source_column']}",
                    "right": f"{rel['target_table']}.{rel['target_column']}",
                    "join_type": "INNER",
                },
                "description": f"FK relation from {rel['source_table']} to {rel['target_table']}.",
                "construction_source": "deterministic_foreign_key",
            }
        )
    return relations


def deterministic_method_candidates(benchmark_spec):
    methods = {}
    for item in benchmark_spec:
        method_id = item.get("method", "")
        if not method_id or method_id == "M_NON_SQL":
            continue
        methods.setdefault(
            method_id,
            {
                "method_id": method_id,
                "business_domain": item.get("group", "unknown"),
                "description": f"Method candidate from benchmark method {method_id}.",
                "target_classes": [],
                "operation_intent": "unknown",
                "required_parameters": [],
                "optional_parameters": [],
                "required_semantics": [],
                "forbidden_semantics": [],
                "example_questions": [],
                "construction_source": "benchmark_spec",
            },
        )
        if item.get("question"):
            methods[method_id]["example_questions"].append(item["question"])
        if item.get("required"):
            methods[method_id]["required_semantics"].append(item["required"])
        if item.get("forbidden"):
            methods[method_id]["forbidden_semantics"].append(item["forbidden"])

    for method in methods.values():
        method["example_questions"] = method["example_questions"][:8]
        method["required_semantics"] = sorted(set(method["required_semantics"]))[:12]
        method["forbidden_semantics"] = sorted(set(method["forbidden_semantics"]))[:12]
    return list(methods.values())


def deterministic_unsupported_candidates(benchmark_spec):
    candidates = []
    for item in benchmark_spec:
        action = item.get("expected_action", "")
        if action not in ["CLARIFY", "REFUSE", "UNSUPPORTED"]:
            continue
        candidates.append(
            {
                "scope_id": item.get("id", "").lower().replace("-", "_"),
                "expected_action": action,
                "question": item.get("question", ""),
                "group": item.get("group", ""),
                "scenario": item.get("scenario", ""),
                "signals": [],
                "reason": item.get("required") or item.get("notes") or "Non-executable SQL action from benchmark.",
                "construction_source": "benchmark_expected_action",
            }
        )
    return candidates


def merge_class_enrichments(classes, enrichments):
    by_table = {item.get("table"): item for item in enrichments}
    for cls in classes:
        enrichment = by_table.get(cls["source_table"])
        if not enrichment:
            continue
        cls["class_name"] = enrichment.get("class_name") or cls["class_name"]
        cls["description"] = enrichment.get("business_description") or cls["description"]
        cls["business_domain"] = enrichment.get("business_domain") or cls["business_domain"]
        cls["class_role"] = enrichment.get("class_role") or cls["class_role"]
        cls["default_display_property"] = enrichment.get("default_display_property")
        cls["llm_confidence"] = enrichment.get("confidence")
        cls["construction_source"] = "deterministic_inventory+llm_enrichment"
    return classes


def build_object_ontology(database_id, inventory_dir, output_dir, use_llm, config_path, proxy_mode):
    inventory_dir = Path(inventory_dir)
    output_dir = Path(output_dir)

    tables = load_json(inventory_dir / "tables.json")
    columns = load_json(inventory_dir / "columns.json")
    relationships = load_json(inventory_dir / "relationships.json")
    sample_values = load_json(inventory_dir / "sample_values.json")
    benchmark_spec = load_json(inventory_dir / "benchmark_spec_snapshot.json")

    classes = deterministic_classes(database_id, tables)
    properties = deterministic_properties(columns)
    relations = deterministic_relations(relationships)
    method_candidates = deterministic_method_candidates(benchmark_spec)
    unsupported_candidates = deterministic_unsupported_candidates(benchmark_spec)

    trace = {
        "database_id": database_id,
        "use_llm": use_llm,
        "config_path": str(config_path),
        "proxy_mode": proxy_mode,
        "deterministic_counts": {
            "classes": len(classes),
            "properties": len(properties),
            "relations": len(relations),
            "method_candidates": len(method_candidates),
            "unsupported_scope_candidates": len(unsupported_candidates),
        },
    }

    if use_llm:
        configure_proxy(proxy_mode)
        columns_by_table = build_column_lookup(columns)
        sample_lookup = build_sample_lookup(sample_values)
        table_cards = compact_table_context(
            tables=tables,
            columns_by_table=columns_by_table,
            sample_lookup=sample_lookup,
            relationships=relationships,
        )
        benchmark_cards = benchmark_context(benchmark_spec)
        llm_output, llm_trace = enrich_object_ontology_with_llm(
            database_id=database_id,
            table_cards=table_cards,
            benchmark_cards=benchmark_cards,
            unsupported_candidates=unsupported_candidates,
            config_path=config_path,
        )

        classes = merge_class_enrichments(classes, llm_output.get("class_enrichments", []))
        if llm_output.get("method_enrichments"):
            method_candidates = [
                item
                for item in llm_output["method_enrichments"]
                if item.get("method_id") != "M_NON_SQL"
            ]
        if llm_output.get("unsupported_scope_candidates"):
            unsupported_candidates = llm_output["unsupported_scope_candidates"]

        trace["llm"] = llm_trace

    manifest = {
        "database_id": database_id,
        "artifact_type": "object_ontology",
        "version": "v01",
        "construction_mode": "hybrid_llm" if use_llm else "deterministic",
        "input_inventory_dir": str(inventory_dir),
        "output_files": {
            "ontology_classes": str(output_dir / "ontology_classes.json"),
            "ontology_properties": str(output_dir / "ontology_properties.json"),
            "ontology_relations": str(output_dir / "ontology_relations.json"),
            "ontology_method_candidates": str(output_dir / "ontology_method_candidates.json"),
            "unsupported_scope_candidates": str(output_dir / "unsupported_scope_candidates.json"),
            "object_ontology_trace": str(output_dir / "object_ontology_trace.json"),
        },
        "counts": {
            "classes": len(classes),
            "properties": len(properties),
            "relations": len(relations),
            "method_candidates": len(method_candidates),
            "unsupported_scope_candidates": len(unsupported_candidates),
        },
    }

    save_json({"database_id": database_id, "classes": classes}, output_dir / "ontology_classes.json")
    save_json({"database_id": database_id, "properties": properties}, output_dir / "ontology_properties.json")
    save_json({"database_id": database_id, "relations": relations}, output_dir / "ontology_relations.json")
    save_json({"database_id": database_id, "method_candidates": method_candidates}, output_dir / "ontology_method_candidates.json")
    save_json({"database_id": database_id, "unsupported_scope_candidates": unsupported_candidates}, output_dir / "unsupported_scope_candidates.json")
    save_json(trace, output_dir / "object_ontology_trace.json")
    save_json(manifest, output_dir / "object_ontology_manifest.json")
    return manifest


def build_parser():
    parser = argparse.ArgumentParser(
        description="Build object ontology from database inventory using deterministic rules and optional LLM enrichment."
    )
    parser.add_argument("--database-id", required=True)
    parser.add_argument("--inventory-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--config-path", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--use-llm", action="store_true")
    parser.add_argument("--proxy-mode", choices=["company", "none"], default="company")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    manifest = build_object_ontology(
        database_id=args.database_id,
        inventory_dir=args.inventory_dir,
        output_dir=args.output_dir,
        use_llm=args.use_llm,
        config_path=Path(args.config_path),
        proxy_mode=args.proxy_mode,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
