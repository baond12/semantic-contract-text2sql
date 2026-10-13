import argparse
import json
from pathlib import Path


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("summary_path")
    args = parser.parse_args()

    summary = load_json(Path(args.summary_path))

    print("SEMANTIC CONTRACT TEXT2SQL")
    print("=" * 60)
    print("Audit:", summary.get("audit_name"))
    print("Execution:", summary.get("audit_execution_status"))
    print("Ontology readiness:", summary.get("ontology_readiness_status"))
    print("Findings:", summary.get("finding_count"))
    print("Tests:", summary.get("test_count"))
    print("Severity:", summary.get("finding_count_by_severity"))
    print("Categories:", summary.get("finding_count_by_category"))


if __name__ == "__main__":
    main()

