import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_json(data, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_result_cols(value):
    if not value:
        return []
    return [item.strip() for item in str(value).split(",") if item.strip()]


def parse_result_preview(value):
    if not value:
        return []
    return json.loads(value)


def build_lookup(items, key):
    return {item[key]: item for item in items if item.get(key)}


def infer_operation_from_question(question, expected_action):
    text = (question or "").lower()
    if expected_action == "CLARIFY":
        return "Clarify"
    if expected_action == "REFUSE":
        return "Refuse"
    if expected_action == "UNSUPPORTED":
        return "Unsupported"
    if any(token in text for token in ["bao nhiêu", "số lượng", "count"]):
        return "Count"
    if any(token in text for token in ["top", "cao nhất", "thấp nhất", "nhiều nhất", "ít nhất", "đắt nhất"]):
        return "Rank"
    if any(token in text for token in ["so sánh", "tăng trưởng", "theo từng", "theo kênh", "theo ngày"]):
        return "Compare"
    if any(token in text for token in ["gmv", "doanh thu", "tổng", "aov", "trung bình"]):
        return "Aggregate"
    if any(token in text for token in ["liệt kê", "danh sách", "những", "các"]):
        return "List"
    return "Lookup"


def group_policy_ids_by_method(semantic_policies):
    grouped = defaultdict(list)
    global_policy_ids = []

    for policy in semantic_policies:
        methods = policy.get("applies_to_methods", [])
        if not methods:
            global_policy_ids.append(policy["policy_id"])
            continue
        for method_id in methods:
            grouped[method_id].append(policy["policy_id"])

    return {
        "by_method": {
            method_id: sorted(set(policy_ids))
            for method_id, policy_ids in grouped.items()
        },
        "global": sorted(set(global_policy_ids)),
    }


def build_benchmark_cases(benchmark_spec, task_scenarios, method_contracts, semantic_policies):
    scenario_by_id = build_lookup(task_scenarios, "scenario_id")
    method_by_id = build_lookup(method_contracts, "method_id")
    policy_ids = group_policy_ids_by_method(semantic_policies)

    cases = []
    for item in benchmark_spec:
        case_id = item["id"]
        expected_action = item.get("expected_action", "")
        method_id = item.get("method", "")
        question_operation_intent = infer_operation_from_question(item.get("question", ""), expected_action)
        scenario = scenario_by_id.get(case_id, {})
        method_contract = method_by_id.get(method_id, {})
        related_policy_ids = policy_ids["global"] if expected_action != "EXECUTE_SQL" else []
        related_policy_ids = sorted(set(related_policy_ids + policy_ids["by_method"].get(method_id, [])))

        case = {
            "case_id": case_id,
            "database_id": item.get("database"),
            "question": item.get("question"),
            "context": item.get("context", ""),
            "group": item.get("group"),
            "scenario": item.get("scenario"),
            "difficulty": item.get("difficulty"),
            "priority": item.get("priority"),
            "expected_action": expected_action,
            "expected_method_id": method_id,
            "expected_business_intent_id": scenario.get("business_intent_id"),
            "expected_operation_intent": question_operation_intent,
            "expected_method_operation_intent": method_contract.get("operation_intent"),
            "expected_target_classes": method_contract.get("target_classes", []),
            "expected_required_slots": method_contract.get("required_slots", []),
            "expected_optional_slots": method_contract.get("optional_slots", []),
            "expected_required_tables": method_contract.get("required_tables", []),
            "expected_required_columns": method_contract.get("required_columns", []),
            "expected_required_relations": method_contract.get("required_relations", []),
            "related_policy_ids": related_policy_ids[:80],
            "gold_sql": item.get("gold_sql", ""),
            "expected_result": {
                "result_cols": parse_result_cols(item.get("result_cols")),
                "expected_row_count": item.get("expected_row_count"),
                "result_preview": parse_result_preview(item.get("result_preview")),
                "result_sha256": item.get("result_sha256", ""),
                "expected_summary": item.get("expected_summary", ""),
            },
            "semantic_expectation": {
                "required": item.get("required", ""),
                "forbidden": item.get("forbidden", ""),
                "notes": item.get("notes", ""),
                "pattern": item.get("pattern", ""),
            },
            "evaluation_targets": build_evaluation_targets(expected_action),
            "construction_source": "benchmark_spec+task_ontology+method_contracts+semantic_policies",
        }
        cases.append(case)
    return cases


def build_evaluation_targets(expected_action):
    if expected_action == "EXECUTE_SQL":
        return {
            "must_generate_sql": True,
            "must_execute_sql": True,
            "must_match_result_hash": True,
            "must_preserve_semantic_contract": True,
            "must_not_execute_sql": False,
        }

    return {
        "must_generate_sql": False,
        "must_execute_sql": False,
        "must_match_result_hash": False,
        "must_preserve_semantic_contract": True,
        "must_not_execute_sql": True,
    }


def split_cases_by_action(cases):
    by_action = defaultdict(list)
    for case in cases:
        by_action[case["expected_action"]].append(case)
    return by_action


def audit_benchmark_cases(cases, method_contracts):
    method_ids = {item["method_id"] for item in method_contracts}
    findings = []

    for case in cases:
        case_id = case["case_id"]
        expected_action = case["expected_action"]
        method_id = case["expected_method_id"]

        if expected_action == "EXECUTE_SQL" and not case.get("gold_sql"):
            findings.append(
                {
                    "severity": "HIGH",
                    "category": "missing_gold_sql",
                    "case_id": case_id,
                    "message": "EXECUTE_SQL case must have gold_sql.",
                }
            )

        if expected_action == "EXECUTE_SQL" and method_id not in method_ids:
            findings.append(
                {
                    "severity": "HIGH",
                    "category": "missing_method_contract",
                    "case_id": case_id,
                    "method_id": method_id,
                    "message": "EXECUTE_SQL case references method_id not found in method contracts.",
                }
            )

        if expected_action != "EXECUTE_SQL" and case.get("gold_sql"):
            findings.append(
                {
                    "severity": "HIGH",
                    "category": "non_sql_case_has_gold_sql",
                    "case_id": case_id,
                    "message": "Non-SQL case should not have gold_sql.",
                }
            )

        if expected_action != "EXECUTE_SQL" and not case["semantic_expectation"].get("required"):
            findings.append(
                {
                    "severity": "MEDIUM",
                    "category": "non_sql_case_missing_expected_message",
                    "case_id": case_id,
                    "message": "Non-SQL case should have required clarification/refusal/unsupported message.",
                }
            )

    return findings


def summarize_cases(cases):
    return {
        "case_count": len(cases),
        "case_count_by_action": dict(sorted(Counter(item["expected_action"] for item in cases).items())),
        "case_count_by_group": dict(sorted(Counter(item["group"] for item in cases).items())),
        "case_count_by_difficulty": dict(sorted(Counter(item["difficulty"] for item in cases).items())),
        "case_count_by_priority": dict(sorted(Counter(item["priority"] for item in cases).items())),
        "case_count_by_method": dict(sorted(Counter(item["expected_method_id"] for item in cases).items())),
    }


def build_benchmark_case_artifacts(
    database_id,
    inventory_dir,
    task_ontology_dir,
    method_contract_dir,
    semantic_policy_dir,
    output_dir,
):
    inventory_dir = Path(inventory_dir)
    task_ontology_dir = Path(task_ontology_dir)
    method_contract_dir = Path(method_contract_dir)
    semantic_policy_dir = Path(semantic_policy_dir)
    output_dir = Path(output_dir)

    benchmark_spec = load_json(inventory_dir / "benchmark_spec_snapshot.json")
    task_scenarios = load_json(task_ontology_dir / "task_scenarios.json")["task_scenarios"]
    method_contracts = load_json(method_contract_dir / "method_contracts.json")["method_contracts"]
    semantic_policies = load_json(semantic_policy_dir / "semantic_policies.json")["semantic_policies"]

    cases = build_benchmark_cases(
        benchmark_spec=benchmark_spec,
        task_scenarios=task_scenarios,
        method_contracts=method_contracts,
        semantic_policies=semantic_policies,
    )
    by_action = split_cases_by_action(cases)
    audit_findings = audit_benchmark_cases(cases, method_contracts)
    summary = summarize_cases(cases)
    readiness_status = "READY" if not [item for item in audit_findings if item["severity"] == "HIGH"] else "NOT_READY"

    manifest = {
        "database_id": database_id,
        "artifact_type": "benchmark_cases",
        "version": "v01",
        "construction_mode": "deterministic",
        "input_inventory_dir": str(inventory_dir),
        "input_task_ontology_dir": str(task_ontology_dir),
        "input_method_contract_dir": str(method_contract_dir),
        "input_semantic_policy_dir": str(semantic_policy_dir),
        "readiness_status": readiness_status,
        "output_files": {
            "benchmark_cases": str(output_dir / "benchmark_cases.json"),
            "benchmark_execution_cases": str(output_dir / "benchmark_execution_cases.json"),
            "benchmark_clarify_cases": str(output_dir / "benchmark_clarify_cases.json"),
            "benchmark_refuse_cases": str(output_dir / "benchmark_refuse_cases.json"),
            "benchmark_unsupported_cases": str(output_dir / "benchmark_unsupported_cases.json"),
            "benchmark_summary": str(output_dir / "benchmark_summary.json"),
            "benchmark_audit": str(output_dir / "benchmark_audit.json"),
        },
        "counts": {
            **summary,
            "audit_findings": len(audit_findings),
            "high_findings": len([item for item in audit_findings if item["severity"] == "HIGH"]),
            "medium_findings": len([item for item in audit_findings if item["severity"] == "MEDIUM"]),
        },
    }

    save_json({"database_id": database_id, "benchmark_cases": cases}, output_dir / "benchmark_cases.json")
    save_json({"database_id": database_id, "benchmark_cases": by_action.get("EXECUTE_SQL", [])}, output_dir / "benchmark_execution_cases.json")
    save_json({"database_id": database_id, "benchmark_cases": by_action.get("CLARIFY", [])}, output_dir / "benchmark_clarify_cases.json")
    save_json({"database_id": database_id, "benchmark_cases": by_action.get("REFUSE", [])}, output_dir / "benchmark_refuse_cases.json")
    save_json({"database_id": database_id, "benchmark_cases": by_action.get("UNSUPPORTED", [])}, output_dir / "benchmark_unsupported_cases.json")
    save_json({"database_id": database_id, "summary": summary}, output_dir / "benchmark_summary.json")
    save_json({"database_id": database_id, "audit_findings": audit_findings}, output_dir / "benchmark_audit.json")
    save_json(manifest, output_dir / "benchmark_manifest.json")
    return manifest


def build_parser():
    parser = argparse.ArgumentParser(
        description="Build normalized benchmark cases for runtime and audit evaluation."
    )
    parser.add_argument("--database-id", required=True)
    parser.add_argument("--inventory-dir", required=True)
    parser.add_argument("--task-ontology-dir", required=True)
    parser.add_argument("--method-contract-dir", required=True)
    parser.add_argument("--semantic-policy-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    manifest = build_benchmark_case_artifacts(
        database_id=args.database_id,
        inventory_dir=Path(args.inventory_dir),
        task_ontology_dir=Path(args.task_ontology_dir),
        method_contract_dir=Path(args.method_contract_dir),
        semantic_policy_dir=Path(args.semantic_policy_dir),
        output_dir=Path(args.output_dir),
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
