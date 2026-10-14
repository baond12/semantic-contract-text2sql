import argparse
import json
from pathlib import Path


REQUIRED_FOLDERS = [
    "00_sources",
    "01_database_inventory",
    "02_object_ontology",
    "03_business_task_ontology",
    "04_method_contracts",
    "05_semantic_policies",
    "06_retrieval_indexes",
    "07_benchmark_cases",
    "08_audit_reports",
    "09_semantic_clustering",
]


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def validate_database_workspace(database_root):
    database_root = Path(database_root)
    findings = []

    if not database_root.exists():
        findings.append({
            "severity": "HIGH",
            "message": f"Workspace does not exist: {database_root}",
        })
        return findings

    manifest_path = database_root / "manifest.json"
    if not manifest_path.exists():
        findings.append({
            "severity": "HIGH",
            "message": "Missing manifest.json",
        })
    else:
        manifest = load_json(manifest_path)
        if not manifest.get("database_id"):
            findings.append({
                "severity": "MEDIUM",
                "message": "manifest.json missing database_id",
            })

    for folder in REQUIRED_FOLDERS:
        folder_path = database_root / folder
        if not folder_path.exists():
            findings.append({
                "severity": "HIGH",
                "message": f"Missing folder: {folder}",
            })

    return findings


def build_parser():
    parser = argparse.ArgumentParser(
        description="Validate standard offline artifact workspace structure."
    )
    parser.add_argument("database_root")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    findings = validate_database_workspace(args.database_root)

    if not findings:
        print("OK: offline artifact workspace structure is valid.")
        return

    print(json.dumps(findings, ensure_ascii=False, indent=2))
    raise SystemExit(1)


if __name__ == "__main__":
    main()
