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


def normalize_operation(value):
    value = (value or "").lower()
    mapping = {
        "count": "COUNT",
        "list": "SELECT",
        "lookup": "SELECT",
        "aggregate": "AGGREGATE",
        "rank": "RANK",
        "compare": "COMPARE",
        "clarify": "CLARIFY",
        "unsupported": "UNSUPPORTED",
        "refuse": "REFUSE",
    }
    return mapping.get(value, "UNKNOWN")


def extract_sql_tables(sql, table_names):
    lowered_sql = (sql or "").lower()
    return sorted({
        table
        for table in table_names
        if re.search(rf"\b{re.escape(table.lower())}\b", lowered_sql)
    })


def extract_sql_columns(sql, column_ids, sql_tables):
    lowered_sql = (sql or "").lower()
    used_columns = []
    for column_id in column_ids:
        table, column = column_id.split(".", 1)
        if table not in sql_tables:
            continue
        table_pattern = re.escape(table.lower())
        column_pattern = re.escape(column.lower())
        if re.search(rf"\b{table_pattern}\.{column_pattern}\b", lowered_sql):
            used_columns.append(column_id)
        elif re.search(rf"\b{column_pattern}\b", lowered_sql):
            used_columns.append(column_id)
    return sorted(set(used_columns))


def extract_sql_features(sql):
    lowered_sql = (sql or "").lower()
    features = []
    checks = [
        ("join", r"\bjoin\b"),
        ("left_join", r"\bleft\s+join\b"),
        ("group_by", r"\bgroup\s+by\b"),
        ("order_by", r"\border\s+by\b"),
        ("limit", r"\blimit\b"),
        ("where", r"\bwhere\b"),
        ("distinct", r"\bdistinct\b"),
        ("window_function", r"\bover\s*\("),
        ("having", r"\bhaving\b"),
        ("cte", r"\bwith\b"),
        ("union", r"\bunion\b"),
    ]
    for feature, pattern in checks:
        if re.search(pattern, lowered_sql):
            features.append(feature)
    if re.search(r"\b(count|sum|avg|min|max)\s*\(", lowered_sql):
        features.append("aggregate_function")
    return sorted(set(features))


def build_lookup(items, key):
    return {item[key]: item for item in items if item.get(key)}


def group_by(items, key):
    grouped = defaultdict(list)
    for item in items:
        grouped[item.get(key, "")].append(item)
    return grouped


def relation_support_for_tables(relations, required_tables):
    selected = []
    for relation in relations:
        left_table = relation["database_mapping"]["left"].split(".", 1)[0]
        right_table = relation["database_mapping"]["right"].split(".", 1)[0]
        if left_table in required_tables and right_table in required_tables:
            selected.append(relation)
    return selected


def build_required_properties(properties, required_columns):
    by_source_column = {item["source_column"]: item for item in properties}
    return [
        by_source_column[column]["property_id"]
        for column in required_columns
        if column in by_source_column
    ]


def build_method_contracts(
    method_candidates,
    business_intents,
    task_slots,
    task_scenarios,
    classes,
    properties,
    relations,
    tables,
    columns,
):
    table_names = {item["table"] for item in tables}
    column_ids = {item["column_id"] for item in columns}
    class_by_id = build_lookup(classes, "class_id")
    slot_by_id = build_lookup(task_slots, "slot_id")
    scenarios_by_method = group_by(task_scenarios, "method_id")

    business_by_method = defaultdict(list)
    for intent in business_intents:
        for method_id in intent.get("allowed_methods", []):
            business_by_method[method_id].append(intent["business_intent_id"])

    soft_required_slot_ids = {"filter_criteria", "metric", "segment_criteria"}
    contracts = []
    for method in method_candidates:
        method_id = method["method_id"]
        scenarios = scenarios_by_method.get(method_id, [])
        execute_scenarios = [item for item in scenarios if item.get("expected_action") == "EXECUTE_SQL"]
        sql_tables_by_scenario = [
            (
                scenario,
                extract_sql_tables(scenario.get("gold_sql", ""), table_names),
            )
            for scenario in execute_scenarios
        ]
        sql_tables = sorted({
            table
            for _, scenario_tables in sql_tables_by_scenario
            for table in scenario_tables
        })
        sql_columns = sorted({
            column
            for scenario, scenario_tables in sql_tables_by_scenario
            for column in extract_sql_columns(scenario.get("gold_sql", ""), column_ids, scenario_tables)
        })
        sql_features = sorted({
            feature
            for scenario in execute_scenarios
            for feature in extract_sql_features(scenario.get("gold_sql", ""))
        })

        class_tables = sorted({
            table
            for class_id in method.get("target_classes", [])
            if class_id in class_by_id
            for table in class_by_id[class_id].get(
                "source_tables",
                [class_by_id[class_id].get("source_table")] if class_by_id[class_id].get("source_table") else [],
            )
        })
        required_tables = sorted(set(sql_tables + class_tables))
        required_properties = build_required_properties(properties, sql_columns)
        required_relations = relation_support_for_tables(relations, set(required_tables))

        required_slots = [
            {
                "slot_id": slot_id,
                "value_type": slot_by_id.get(slot_id, {}).get("value_type", "unknown"),
                "required": True,
            }
            for slot_id in method.get("required_parameters", [])
            if slot_id not in soft_required_slot_ids
        ]
        optional_slots = [
            {
                "slot_id": slot_id,
                "value_type": slot_by_id.get(slot_id, {}).get("value_type", "unknown"),
                "required": False,
            }
            for slot_id in sorted(set(method.get("optional_parameters", []) + [
                item
                for item in method.get("required_parameters", [])
                if item in soft_required_slot_ids
            ]))
        ]

        required_semantics = sorted({
            item
            for item in method.get("required_semantics", [])
            if item
        } | {
            item.get("required_semantics")
            for item in scenarios
            if item.get("required_semantics")
        })
        forbidden_semantics = sorted({
            item
            for item in method.get("forbidden_semantics", [])
            if item
        } | {
            item.get("forbidden_semantics")
            for item in scenarios
            if item.get("forbidden_semantics")
        })

        expected_actions = Counter(item.get("expected_action", "") for item in scenarios)
        contracts.append(
            {
                "method_id": method_id,
                "business_domain": method.get("business_domain"),
                "description": method.get("description"),
                "business_intent_ids": sorted(set(business_by_method.get(method_id, []))),
                "operation_intent": method.get("operation_intent"),
                "method_owner_class": method.get("method_owner_class"),
                "method_scope": method.get("method_scope"),
                "allowed_sql_operation": normalize_operation(method.get("operation_intent")),
                "target_classes": method.get("target_classes", []),
                "required_tables": required_tables,
                "required_properties": required_properties,
                "required_columns": sql_columns,
                "required_relations": [
                    {
                        "relation_id": item["relation_id"],
                        "left": item["database_mapping"]["left"],
                        "right": item["database_mapping"]["right"],
                        "join_type": item["database_mapping"]["join_type"],
                    }
                    for item in required_relations
                ],
                "required_slots": required_slots,
                "optional_slots": optional_slots,
                "required_semantics": required_semantics,
                "forbidden_semantics": forbidden_semantics,
                "observed_sql_features": sql_features,
                "validation_rules": [
                    "Preserve every required slot in SQL planning or ask clarification.",
                    "Use only tables/properties allowed by this method contract unless validator approves expansion.",
                    "Do not violate forbidden_semantics.",
                    "If expected action is CLARIFY, REFUSE, or UNSUPPORTED, do not execute SQL.",
                ],
                "example_scenarios": [
                    {
                        "scenario_id": item.get("scenario_id"),
                        "question": item.get("question"),
                        "expected_action": item.get("expected_action"),
                        "difficulty": item.get("difficulty"),
                        "required_semantics": item.get("required_semantics"),
                        "forbidden_semantics": item.get("forbidden_semantics"),
                    }
                    for item in scenarios[:8]
                ],
                "scenario_count": len(scenarios),
                "expected_action_distribution": dict(expected_actions),
                "risk_notes": [],
                "confidence": method.get("confidence", 0.0),
                "construction_source": "object_ontology+task_ontology+benchmark_spec",
            }
        )

    return sorted(contracts, key=lambda item: item["method_id"])


METHOD_CONTRACT_ENRICHMENT_CONTRACT = {
    "method_contract_enrichments": [
        {
            "method_id": "same method id from input",
            "business_meaning": "short Vietnamese explanation",
            "semantic_guardrails": [],
            "common_failure_modes": [],
            "minimum_required_context": [],
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
Bạn là semantic contract architect cho Text2SQL trong môi trường industry.

Nhiệm vụ:
- Đọc method contracts được sinh tự động.
- Bổ sung guardrail ngữ nghĩa, lỗi thường gặp, minimum context.
- Không đổi method_id.
- Không sinh SQL.
- Không tạo class/table/column mới.
- Trả về JSON đúng contract.
- Viết ngắn gọn, không giải thích ngoài JSON.
"""
    user_prompt = f"""
TASK:
{task_name}

CONTRACT:
{json.dumps(contract, ensure_ascii=False, indent=2)}

CONTEXT:
{json.dumps(context, ensure_ascii=False, indent=2)}

Return only JSON.
"""
    raw_output = call_llm(system_prompt, user_prompt, config_path)
    parsed = extract_json_object(raw_output)
    return parsed, raw_output, system_prompt, user_prompt


def merge_method_contract_enrichments(method_contracts, enrichments):
    by_id = {item.get("method_id"): item for item in enrichments}
    for contract in method_contracts:
        enrichment = by_id.get(contract["method_id"])
        if not enrichment:
            continue
        contract["business_meaning"] = enrichment.get("business_meaning", "")
        contract["semantic_guardrails"] = enrichment.get("semantic_guardrails", [])
        contract["common_failure_modes"] = enrichment.get("common_failure_modes", [])
        contract["minimum_required_context"] = enrichment.get("minimum_required_context", [])
        contract["llm_confidence"] = enrichment.get("confidence")
        contract["construction_source"] = contract["construction_source"] + "+llm_enrichment"
    return method_contracts


def audit_method_contracts(method_contracts, method_candidates, classes, task_slots):
    method_ids = {item["method_id"] for item in method_candidates}
    class_ids = {item["class_id"] for item in classes}
    slot_ids = {item["slot_id"] for item in task_slots}
    findings = []

    for contract in method_contracts:
        method_id = contract["method_id"]
        if method_id not in method_ids:
            findings.append(
                {
                    "severity": "HIGH",
                    "category": "missing_method",
                    "method_id": method_id,
                    "message": "Method contract references method_id not found in object ontology.",
                }
            )

        for class_id in contract.get("target_classes", []):
            if class_id not in class_ids:
                findings.append(
                    {
                        "severity": "HIGH",
                        "category": "missing_class",
                        "method_id": method_id,
                        "class_id": class_id,
                        "message": "Method contract references class_id not found in object ontology.",
                    }
                )

        for slot in contract.get("required_slots", []) + contract.get("optional_slots", []):
            if slot["slot_id"] not in slot_ids:
                findings.append(
                    {
                        "severity": "HIGH",
                        "category": "missing_slot",
                        "method_id": method_id,
                        "slot_id": slot["slot_id"],
                        "message": "Method contract references slot_id not found in task ontology.",
                    }
                )

        if not contract.get("target_classes"):
            findings.append(
                {
                    "severity": "MEDIUM",
                    "category": "empty_target_classes",
                    "method_id": method_id,
                    "message": "Method contract has no target classes.",
                }
            )

    return findings


def build_method_contract_artifacts(
    database_id,
    inventory_dir,
    object_ontology_dir,
    task_ontology_dir,
    output_dir,
    use_llm,
    config_path,
    proxy_mode,
):
    inventory_dir = Path(inventory_dir)
    object_ontology_dir = Path(object_ontology_dir)
    task_ontology_dir = Path(task_ontology_dir)
    output_dir = Path(output_dir)

    tables = load_json(inventory_dir / "tables.json")
    columns = load_json(inventory_dir / "columns.json")
    classes = load_json(object_ontology_dir / "ontology_classes.json")["classes"]
    derived_classes_path = object_ontology_dir / "ontology_derived_classes.json"
    if derived_classes_path.exists():
        derived_classes = load_json(derived_classes_path)["derived_classes"]
    else:
        derived_classes = []
    all_classes = classes + derived_classes
    properties = load_json(object_ontology_dir / "ontology_properties.json")["properties"]
    relations = load_json(object_ontology_dir / "ontology_relations.json")["relations"]
    method_candidates = load_json(object_ontology_dir / "ontology_method_candidates.json")["method_candidates"]
    business_intents = load_json(task_ontology_dir / "business_intents.json")["business_intents"]
    task_slots = load_json(task_ontology_dir / "task_slots.json")["task_slots"]
    task_scenarios = load_json(task_ontology_dir / "task_scenarios.json")["task_scenarios"]

    method_contracts = build_method_contracts(
        method_candidates=method_candidates,
        business_intents=business_intents,
        task_slots=task_slots,
        task_scenarios=task_scenarios,
        classes=all_classes,
        properties=properties,
        relations=relations,
        tables=tables,
        columns=columns,
    )

    trace = {
        "database_id": database_id,
        "use_llm": use_llm,
        "config_path": str(config_path),
        "proxy_mode": proxy_mode,
        "deterministic_counts": {
            "method_contracts": len(method_contracts),
        },
    }

    if use_llm:
        configure_proxy(proxy_mode)
        llm_context = {
            "database_id": database_id,
            "method_contracts": [
                {
                    "method_id": item["method_id"],
                    "description": item.get("description"),
                    "operation_intent": item.get("operation_intent"),
                    "method_owner_class": item.get("method_owner_class"),
                    "method_scope": item.get("method_scope"),
                    "target_classes": item.get("target_classes"),
                    "required_slots": item.get("required_slots"),
                    "optional_slots": item.get("optional_slots"),
                    "required_semantics": item.get("required_semantics"),
                    "forbidden_semantics": item.get("forbidden_semantics"),
                    "observed_sql_features": item.get("observed_sql_features"),
                    "example_scenarios": item.get("example_scenarios", [])[:4],
                }
                for item in method_contracts
            ],
        }
        llm_output, raw_output, system_prompt, user_prompt = call_json_llm(
            task_name="Enrich method contracts with semantic guardrails.",
            contract=METHOD_CONTRACT_ENRICHMENT_CONTRACT,
            context=llm_context,
            config_path=config_path,
        )
        method_contracts = merge_method_contract_enrichments(
            method_contracts,
            llm_output.get("method_contract_enrichments", []),
        )
        trace["llm"] = {
            "raw_output": raw_output,
            "parsed_output": llm_output,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
        }

    audit_findings = audit_method_contracts(
        method_contracts=method_contracts,
        method_candidates=method_candidates,
        classes=all_classes,
        task_slots=task_slots,
    )
    readiness_status = "READY" if not [item for item in audit_findings if item["severity"] == "HIGH"] else "NOT_READY"

    manifest = {
        "database_id": database_id,
        "artifact_type": "method_contracts",
        "version": "v01",
        "construction_mode": "hybrid_llm" if use_llm else "deterministic",
        "input_inventory_dir": str(inventory_dir),
        "input_object_ontology_dir": str(object_ontology_dir),
        "input_task_ontology_dir": str(task_ontology_dir),
        "readiness_status": readiness_status,
        "output_files": {
            "method_contracts": str(output_dir / "method_contracts.json"),
            "method_contract_audit": str(output_dir / "method_contract_audit.json"),
            "method_contract_trace": str(output_dir / "method_contract_trace.json"),
        },
        "counts": {
            "method_contracts": len(method_contracts),
            "audit_findings": len(audit_findings),
            "high_findings": len([item for item in audit_findings if item["severity"] == "HIGH"]),
            "medium_findings": len([item for item in audit_findings if item["severity"] == "MEDIUM"]),
        },
    }

    save_json({"database_id": database_id, "method_contracts": method_contracts}, output_dir / "method_contracts.json")
    save_json({"database_id": database_id, "audit_findings": audit_findings}, output_dir / "method_contract_audit.json")
    save_json(trace, output_dir / "method_contract_trace.json")
    save_json(manifest, output_dir / "method_contract_manifest.json")
    return manifest


def build_parser():
    parser = argparse.ArgumentParser(
        description="Build method contracts from object ontology, task ontology, and benchmark scenarios."
    )
    parser.add_argument("--database-id", required=True)
    parser.add_argument("--inventory-dir", required=True)
    parser.add_argument("--object-ontology-dir", required=True)
    parser.add_argument("--task-ontology-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--config-path", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--use-llm", action="store_true")
    parser.add_argument("--proxy-mode", choices=["company", "none"], default="company")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    manifest = build_method_contract_artifacts(
        database_id=args.database_id,
        inventory_dir=args.inventory_dir,
        object_ontology_dir=args.object_ontology_dir,
        task_ontology_dir=args.task_ontology_dir,
        output_dir=args.output_dir,
        use_llm=args.use_llm,
        config_path=Path(args.config_path),
        proxy_mode=args.proxy_mode,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
