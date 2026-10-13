import argparse
import json
from pathlib import Path

from semantic_contract_text2sql.io import load_json


def print_audit_summary(path: Path) -> None:
    summary = load_json(path)

    print("SEMANTIC CONTRACT TEXT2SQL")
    print("=" * 60)
    print("Audit:", summary.get("audit_name", ""))
    print("Execution:", summary.get("audit_execution_status", ""))
    print("Ontology readiness:", summary.get("ontology_readiness_status", ""))
    print("Findings:", summary.get("finding_count", ""))
    print("Tests:", summary.get("test_count", ""))
    print()
    print("Severity:")
    print(json.dumps(summary.get("finding_count_by_severity", {}), ensure_ascii=False, indent=2))
    print()
    print("Categories:")
    print(json.dumps(summary.get("finding_count_by_category", {}), ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="semantic-contract-text2sql",
        description="Utilities for ontology-based semantic contract audit in Text2SQL.",
    )
    parser.add_argument(
        "summary_path",
        nargs="?",
        help="Path to audit_summary.json.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not args.summary_path:
        parser.print_help()
        return

    print_audit_summary(Path(args.summary_path))


if __name__ == "__main__":
    main()

