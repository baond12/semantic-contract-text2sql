import argparse
import json
from collections import Counter
from pathlib import Path


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_json(data, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def save_text(text, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def file_status(path, required=True):
    path = Path(path)
    return {
        "path": str(path),
        "required": required,
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() else 0,
    }


def load_manifest(path, artifact_name):
    path = Path(path)
    if not path.exists():
        return {
            "artifact_name": artifact_name,
            "readiness_status": "MISSING",
            "counts": {},
            "path": str(path),
        }
    manifest = load_json(path)
    manifest["artifact_name"] = artifact_name
    manifest["path"] = str(path)
    manifest["readiness_status"] = manifest.get("readiness_status", "READY")
    return manifest


def build_artifact_manifest_index(root):
    root = Path(root)
    artifact_specs = [
        ("01_database_inventory", root / "01_database_inventory" / "database_overview.json"),
        ("02_object_ontology", root / "02_object_ontology" / "object_ontology_manifest.json"),
        ("03_business_task_ontology", root / "03_business_task_ontology" / "task_ontology_manifest.json"),
        ("04_method_contracts", root / "04_method_contracts" / "method_contract_manifest.json"),
        ("05_semantic_policies", root / "05_semantic_policies" / "semantic_policy_manifest.json"),
        ("06_retrieval_indexes", root / "06_retrieval_indexes" / "retrieval_manifest.json"),
        ("07_benchmark_cases", root / "07_benchmark_cases" / "benchmark_manifest.json"),
    ]
    return [
        load_manifest(path, artifact_name)
        for artifact_name, path in artifact_specs
    ]


def required_files(root):
    root = Path(root)
    paths = [
        root / "01_database_inventory" / "tables.json",
        root / "01_database_inventory" / "columns.json",
        root / "01_database_inventory" / "relationships.json",
        root / "01_database_inventory" / "benchmark_spec_snapshot.json",
        root / "02_object_ontology" / "ontology_classes.json",
        root / "02_object_ontology" / "ontology_properties.json",
        root / "02_object_ontology" / "ontology_relations.json",
        root / "02_object_ontology" / "ontology_method_candidates.json",
        root / "03_business_task_ontology" / "business_intents.json",
        root / "03_business_task_ontology" / "operation_intents.json",
        root / "03_business_task_ontology" / "task_slots.json",
        root / "03_business_task_ontology" / "task_scenarios.json",
        root / "04_method_contracts" / "method_contracts.json",
        root / "05_semantic_policies" / "semantic_policies.json",
        root / "06_retrieval_indexes" / "retrieval_cards.json",
        root / "06_retrieval_indexes" / "bm25_index.json",
        root / "07_benchmark_cases" / "benchmark_cases.json",
    ]
    return [file_status(path) for path in paths]


def read_core_artifacts(root):
    root = Path(root)
    return {
        "tables": load_json(root / "01_database_inventory" / "tables.json"),
        "columns": load_json(root / "01_database_inventory" / "columns.json"),
        "relationships": load_json(root / "01_database_inventory" / "relationships.json"),
        "classes": load_json(root / "02_object_ontology" / "ontology_classes.json")["classes"],
        "properties": load_json(root / "02_object_ontology" / "ontology_properties.json")["properties"],
        "relations": load_json(root / "02_object_ontology" / "ontology_relations.json")["relations"],
        "methods": load_json(root / "02_object_ontology" / "ontology_method_candidates.json")["method_candidates"],
        "business_intents": load_json(root / "03_business_task_ontology" / "business_intents.json")["business_intents"],
        "operation_intents": load_json(root / "03_business_task_ontology" / "operation_intents.json")["operation_intents"],
        "task_slots": load_json(root / "03_business_task_ontology" / "task_slots.json")["task_slots"],
        "task_scenarios": load_json(root / "03_business_task_ontology" / "task_scenarios.json")["task_scenarios"],
        "method_contracts": load_json(root / "04_method_contracts" / "method_contracts.json")["method_contracts"],
        "semantic_policies": load_json(root / "05_semantic_policies" / "semantic_policies.json")["semantic_policies"],
        "retrieval_cards": load_json(root / "06_retrieval_indexes" / "retrieval_cards.json")["retrieval_cards"],
        "benchmark_cases": load_json(root / "07_benchmark_cases" / "benchmark_cases.json")["benchmark_cases"],
    }


def audit_cross_layer(artifacts):
    findings = []
    table_names = {item["table"] for item in artifacts["tables"]}
    column_ids = {item["column_id"] for item in artifacts["columns"]}
    class_ids = {item["class_id"] for item in artifacts["classes"]}
    property_ids = {item["property_id"] for item in artifacts["properties"]}
    relation_ids = {item["relation_id"] for item in artifacts["relations"]}
    method_ids = {item["method_id"] for item in artifacts["methods"]}
    contract_method_ids = {item["method_id"] for item in artifacts["method_contracts"]}
    business_intent_ids = {item["business_intent_id"] for item in artifacts["business_intents"]}
    operation_intent_ids = {item["operation_intent_id"] for item in artifacts["operation_intents"]}
    task_slot_ids = {item["slot_id"] for item in artifacts["task_slots"]}
    policy_ids = {item["policy_id"] for item in artifacts["semantic_policies"]}
    retrieval_card_ids = {item["card_id"] for item in artifacts["retrieval_cards"]}

    for cls in artifacts["classes"]:
        if cls.get("source_table") not in table_names:
            findings.append(high("class_missing_source_table", cls["class_id"], cls.get("source_table")))

    for prop in artifacts["properties"]:
        if prop.get("class_id") not in class_ids:
            findings.append(high("property_missing_class", prop["property_id"], prop.get("class_id")))
        if prop.get("source_column") not in column_ids:
            findings.append(high("property_missing_source_column", prop["property_id"], prop.get("source_column")))

    for relation in artifacts["relations"]:
        if relation.get("source_class") not in class_ids:
            findings.append(high("relation_missing_source_class", relation["relation_id"], relation.get("source_class")))
        if relation.get("target_class") not in class_ids:
            findings.append(high("relation_missing_target_class", relation["relation_id"], relation.get("target_class")))
        if relation.get("source_property") not in property_ids:
            findings.append(high("relation_missing_source_property", relation["relation_id"], relation.get("source_property")))
        if relation.get("target_property") not in property_ids:
            findings.append(high("relation_missing_target_property", relation["relation_id"], relation.get("target_property")))

    for method in artifacts["methods"]:
        for class_id in method.get("target_classes", []):
            if class_id not in class_ids:
                findings.append(high("method_missing_target_class", method["method_id"], class_id))

    for intent in artifacts["business_intents"]:
        for method_id in intent.get("allowed_methods", []):
            if method_id not in method_ids:
                findings.append(high("business_intent_missing_method", intent["business_intent_id"], method_id))
        for class_id in intent.get("related_classes", []):
            if class_id not in class_ids:
                findings.append(high("business_intent_missing_class", intent["business_intent_id"], class_id))
        for operation_id in intent.get("allowed_operation_intents", []):
            if operation_id not in operation_intent_ids:
                findings.append(high("business_intent_missing_operation", intent["business_intent_id"], operation_id))
        for slot_id in intent.get("required_slots", []) + intent.get("optional_slots", []):
            if slot_id not in task_slot_ids:
                findings.append(high("business_intent_missing_slot", intent["business_intent_id"], slot_id))

    for contract in artifacts["method_contracts"]:
        method_id = contract["method_id"]
        if method_id not in method_ids:
            findings.append(high("contract_missing_method", method_id, method_id))
        for intent_id in contract.get("business_intent_ids", []):
            if intent_id not in business_intent_ids:
                findings.append(high("contract_missing_business_intent", method_id, intent_id))
        for class_id in contract.get("target_classes", []):
            if class_id not in class_ids:
                findings.append(high("contract_missing_class", method_id, class_id))
        for table in contract.get("required_tables", []):
            if table not in table_names:
                findings.append(high("contract_missing_table", method_id, table))
        for column in contract.get("required_columns", []):
            if column not in column_ids:
                findings.append(high("contract_missing_column", method_id, column))
        for prop in contract.get("required_properties", []):
            if prop not in property_ids:
                findings.append(high("contract_missing_property", method_id, prop))
        for rel in contract.get("required_relations", []):
            if rel.get("relation_id") not in relation_ids:
                findings.append(high("contract_missing_relation", method_id, rel.get("relation_id")))
        for slot in contract.get("required_slots", []) + contract.get("optional_slots", []):
            if slot.get("slot_id") not in task_slot_ids:
                findings.append(high("contract_missing_slot", method_id, slot.get("slot_id")))

    for policy in artifacts["semantic_policies"]:
        for method_id in policy.get("applies_to_methods", []):
            if method_id not in contract_method_ids:
                findings.append(high("policy_missing_method_contract", policy["policy_id"], method_id))

    for case in artifacts["benchmark_cases"]:
        case_id = case["case_id"]
        if case.get("expected_action") == "EXECUTE_SQL":
            if case.get("expected_method_id") not in contract_method_ids:
                findings.append(high("benchmark_missing_method_contract", case_id, case.get("expected_method_id")))
            if not case.get("gold_sql"):
                findings.append(high("benchmark_missing_gold_sql", case_id, "gold_sql"))
        else:
            if case.get("gold_sql"):
                findings.append(high("benchmark_non_sql_has_gold_sql", case_id, "gold_sql"))
        if case.get("expected_business_intent_id") and case.get("expected_business_intent_id") not in business_intent_ids:
            findings.append(high("benchmark_missing_business_intent", case_id, case.get("expected_business_intent_id")))
        for policy_id in case.get("related_policy_ids", []):
            if policy_id not in policy_ids:
                findings.append(high("benchmark_missing_policy", case_id, policy_id))

    expected_card_prefixes = [
        "business_intent:",
        "class:",
        "method:",
        "operation_intent:",
        "property:",
        "semantic_policy:",
        "task_slot:",
        "task_value:",
    ]
    for prefix in expected_card_prefixes:
        if not any(card_id.startswith(prefix) for card_id in retrieval_card_ids):
            findings.append(high("retrieval_missing_card_type", "retrieval_cards", prefix))

    return findings


def high(category, owner_id, missing_ref):
    return {
        "severity": "HIGH",
        "category": category,
        "owner_id": owner_id,
        "missing_ref": missing_ref,
    }


def build_coverage_summary(artifacts):
    table_names = {item["table"] for item in artifacts["tables"]}
    column_ids = {item["column_id"] for item in artifacts["columns"]}
    class_table_names = {item.get("source_table") for item in artifacts["classes"]}
    property_column_ids = {item.get("source_column") for item in artifacts["properties"]}
    contract_tables = {
        table
        for item in artifacts["method_contracts"]
        for table in item.get("required_tables", [])
    }
    contract_columns = {
        column
        for item in artifacts["method_contracts"]
        for column in item.get("required_columns", [])
    }

    return {
        "table_count": len(table_names),
        "column_count": len(column_ids),
        "class_count": len(artifacts["classes"]),
        "property_count": len(artifacts["properties"]),
        "method_count": len(artifacts["methods"]),
        "method_contract_count": len(artifacts["method_contracts"]),
        "semantic_policy_count": len(artifacts["semantic_policies"]),
        "retrieval_card_count": len(artifacts["retrieval_cards"]),
        "benchmark_case_count": len(artifacts["benchmark_cases"]),
        "object_ontology_table_coverage": round(len(table_names & class_table_names) / max(1, len(table_names)), 4),
        "object_ontology_column_coverage": round(len(column_ids & property_column_ids) / max(1, len(column_ids)), 4),
        "method_contract_table_coverage": round(len(table_names & contract_tables) / max(1, len(table_names)), 4),
        "method_contract_column_coverage": round(len(column_ids & contract_columns) / max(1, len(column_ids)), 4),
    }


def build_readiness_report(database_id, root, output_dir):
    root = Path(root)
    output_dir = Path(output_dir)

    artifact_manifest_index = build_artifact_manifest_index(root)
    required_file_status = required_files(root)
    missing_required_files = [item for item in required_file_status if item["required"] and not item["exists"]]

    artifacts = read_core_artifacts(root)
    cross_layer_findings = audit_cross_layer(artifacts)
    coverage_summary = build_coverage_summary(artifacts)
    manifest_status_counts = Counter(item.get("readiness_status", "UNKNOWN") for item in artifact_manifest_index)

    high_findings = [item for item in cross_layer_findings if item["severity"] == "HIGH"]
    readiness_status = "READY"
    if missing_required_files or high_findings:
        readiness_status = "NOT_READY"
    if any(item.get("readiness_status") in ["NOT_READY", "MISSING"] for item in artifact_manifest_index):
        readiness_status = "NOT_READY"

    report = {
        "database_id": database_id,
        "artifact_type": "offline_readiness_report",
        "version": "v01",
        "readiness_status": readiness_status,
        "artifact_manifest_status_counts": dict(sorted(manifest_status_counts.items())),
        "coverage_summary": coverage_summary,
        "missing_required_file_count": len(missing_required_files),
        "cross_layer_finding_count": len(cross_layer_findings),
        "high_finding_count": len(high_findings),
        "next_phase_recommendation": build_next_phase_recommendation(readiness_status),
        "output_files": {
            "offline_readiness_report": str(output_dir / "offline_readiness_report.json"),
            "offline_readiness_summary": str(output_dir / "offline_readiness_summary.md"),
            "artifact_manifest_index": str(output_dir / "artifact_manifest_index.json"),
            "cross_layer_audit": str(output_dir / "cross_layer_audit.json"),
            "required_file_status": str(output_dir / "required_file_status.json"),
        },
    }

    summary_text = render_summary(report, artifact_manifest_index, coverage_summary, cross_layer_findings)

    save_json(report, output_dir / "offline_readiness_report.json")
    save_text(summary_text, output_dir / "offline_readiness_summary.md")
    save_json({"database_id": database_id, "artifact_manifests": artifact_manifest_index}, output_dir / "artifact_manifest_index.json")
    save_json({"database_id": database_id, "audit_findings": cross_layer_findings}, output_dir / "cross_layer_audit.json")
    save_json({"database_id": database_id, "required_files": required_file_status}, output_dir / "required_file_status.json")
    return report


def build_next_phase_recommendation(readiness_status):
    if readiness_status == "READY":
        return "Proceed to online runtime PoC: retrieve candidates -> build small context -> parse task state -> validate -> method call."
    return "Fix HIGH findings before building online runtime."


def render_summary(report, artifact_manifest_index, coverage_summary, cross_layer_findings):
    lines = [
        f"# Offline Readiness Summary - {report['database_id']}",
        "",
        f"Readiness: **{report['readiness_status']}**",
        "",
        "## Artifact Status",
        "",
    ]
    for item in artifact_manifest_index:
        status = item.get("readiness_status", "READY" if item["artifact_name"] == "01_database_inventory" else "UNKNOWN")
        lines.append(f"- `{item['artifact_name']}`: `{status}`")

    lines.extend(
        [
            "",
            "## Coverage",
            "",
            f"- Tables: `{coverage_summary['table_count']}`",
            f"- Columns: `{coverage_summary['column_count']}`",
            f"- Classes: `{coverage_summary['class_count']}`",
            f"- Properties: `{coverage_summary['property_count']}`",
            f"- Method contracts: `{coverage_summary['method_contract_count']}`",
            f"- Semantic policies: `{coverage_summary['semantic_policy_count']}`",
            f"- Retrieval cards: `{coverage_summary['retrieval_card_count']}`",
            f"- Benchmark cases: `{coverage_summary['benchmark_case_count']}`",
            f"- Object ontology table coverage: `{coverage_summary['object_ontology_table_coverage']}`",
            f"- Object ontology column coverage: `{coverage_summary['object_ontology_column_coverage']}`",
            f"- Method contract table coverage: `{coverage_summary['method_contract_table_coverage']}`",
            f"- Method contract column coverage: `{coverage_summary['method_contract_column_coverage']}`",
            "",
            "## Audit",
            "",
            f"- Cross-layer findings: `{len(cross_layer_findings)}`",
            f"- High findings: `{report['high_finding_count']}`",
            "",
            "## Next Step",
            "",
            report["next_phase_recommendation"],
            "",
        ]
    )
    return "\n".join(lines)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Build offline readiness report across all offline artifacts."
    )
    parser.add_argument("--database-id", required=True)
    parser.add_argument("--offline-root", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    report = build_readiness_report(
        database_id=args.database_id,
        root=Path(args.offline_root),
        output_dir=Path(args.output_dir),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
