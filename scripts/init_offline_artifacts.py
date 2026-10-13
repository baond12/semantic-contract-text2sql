import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


OFFLINE_FOLDERS = [
    "00_sources",
    "01_database_inventory",
    "02_object_ontology",
    "03_business_task_ontology",
    "04_method_contracts",
    "05_semantic_policies",
    "06_retrieval_indexes",
    "07_benchmark_cases",
    "08_audit_reports",
]


FOLDER_DESCRIPTIONS = {
    "00_sources": "Raw schema, metadata, DDL, business documents, scenario/testcase sources.",
    "01_database_inventory": "Normalized database inventory: tables, columns, relationships, values.",
    "02_object_ontology": "Object ontology: classes, properties, relations, methods, SQL templates.",
    "03_business_task_ontology": "Task ontology: business intents, operation intents, slots, values, examples.",
    "04_method_contracts": "Mappings from task ontology to object ontology methods and SQL templates.",
    "05_semantic_policies": "Required/forbidden semantics, metric definitions, join/time/security policies.",
    "06_retrieval_indexes": "BM25/vector indexes and retrieval cards for scalable online context selection.",
    "07_benchmark_cases": "Scenario matrix, test cases, gold SQL, expected results, scoring rules.",
    "08_audit_reports": "Readiness, coverage, consistency, method-contract, and semantic-policy reports.",
}


def write_json(data, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_readme(path, title, description):
    content = f"# {title}\n\n{description}\n"
    path.write_text(content, encoding="utf-8")


def copy_sources(source_paths, target_dir):
    copied = []
    for source_path in source_paths:
        source_path = Path(source_path)
        target_path = target_dir / source_path.name
        if source_path.is_dir():
            shutil.copytree(source_path, target_path, dirs_exist_ok=True)
        else:
            shutil.copy2(source_path, target_path)
        copied.append(str(target_path))
    return copied


def init_offline_artifacts(database_id, output_root, source_paths):
    output_root = Path(output_root)
    database_root = output_root / database_id
    database_root.mkdir(parents=True, exist_ok=True)

    for folder in OFFLINE_FOLDERS:
        folder_path = database_root / folder
        folder_path.mkdir(parents=True, exist_ok=True)
        readme_path = folder_path / "README.md"
        if not readme_path.exists():
            write_readme(readme_path, folder, FOLDER_DESCRIPTIONS[folder])

    copied_sources = copy_sources(source_paths, database_root / "00_sources")

    manifest = {
        "database_id": database_id,
        "artifact_type": "offline_database_workspace",
        "version": "v01",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "folders": OFFLINE_FOLDERS,
        "copied_sources": copied_sources,
        "next_steps": [
            "Build 01_database_inventory from raw sources.",
            "Build or copy 02_object_ontology.",
            "Build 03_business_task_ontology.",
            "Connect task ontology to object ontology in 04_method_contracts.",
            "Define semantic policies in 05_semantic_policies.",
            "Build retrieval cards/indexes in 06_retrieval_indexes.",
            "Add benchmark cases in 07_benchmark_cases.",
            "Run audit and save reports in 08_audit_reports."
        ],
    }
    write_json(manifest, database_root / "manifest.json")

    return database_root


def build_parser():
    parser = argparse.ArgumentParser(
        description="Initialize offline artifact workspace for one Text2SQL database."
    )
    parser.add_argument("--database-id", required=True)
    parser.add_argument("--output-root", default="offline_artifacts")
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        help="Optional source file/folder to copy into 00_sources. Can be used multiple times.",
    )
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    database_root = init_offline_artifacts(
        database_id=args.database_id,
        output_root=args.output_root,
        source_paths=args.source,
    )

    print("CREATED:", database_root)
    print("NEXT:", database_root / "README.md")


if __name__ == "__main__":
    main()

