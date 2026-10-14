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


def text_to_id(text, suffix=""):
    words = re.findall(r"[A-Za-z0-9]+", text)
    if not words:
        return "Unknown" + suffix
    value = "".join(word[:1].upper() + word[1:] for word in words)
    if suffix and not value.endswith(suffix):
        value += suffix
    return value


def normalize_operation_intent(value):
    value = (value or "").lower().strip()
    mapping = {
        "count": "Count",
        "list": "List",
        "lookup": "Lookup",
        "aggregate": "Aggregate",
        "rank": "Rank",
        "compare": "Compare",
        "clarify": "Clarify",
        "unsupported": "Unsupported",
        "refuse": "Refuse",
    }
    return mapping.get(value, "Unknown")


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


def build_method_lookup(method_candidates):
    return {
        item["method_id"]: item
        for item in method_candidates
        if item.get("method_id") and item.get("method_id") != "M_NON_SQL"
    }


def build_business_intents(benchmark_spec, method_lookup):
    group_items = defaultdict(list)
    for item in benchmark_spec:
        group_items[item.get("group", "Other")].append(item)

    business_intents = []
    for group, items in sorted(group_items.items()):
        methods = sorted({item.get("method", "") for item in items if item.get("method") and item.get("method") != "M_NON_SQL"})
        related_classes = sorted({
            cls
            for method_id in methods
            for cls in method_lookup.get(method_id, {}).get("target_classes", [])
        })
        expected_actions = Counter(item.get("expected_action", "") for item in items)
        difficulties = Counter(item.get("difficulty", "") for item in items)
        sample_questions = [item.get("question", "") for item in items[:6]]

        business_intents.append(
            {
                "business_intent_id": text_to_id(group, "Intent"),
                "business_intent_name": group,
                "source_group": group,
                "description": f"Business intent built from benchmark group {group}.",
                "related_classes": related_classes,
                "allowed_methods": methods,
                "expected_actions": dict(expected_actions),
                "difficulty_distribution": dict(difficulties),
                "sample_questions": sample_questions,
                "construction_source": "benchmark_group",
            }
        )
    return business_intents


def build_operation_intents(benchmark_spec, method_lookup):
    operation_sources = defaultdict(list)

    for method in method_lookup.values():
        operation_sources[normalize_operation_intent(method.get("operation_intent"))].append(method.get("method_id"))

    for item in benchmark_spec:
        operation = infer_operation_from_question(item.get("question", ""), item.get("expected_action", ""))
        operation_sources[operation].append(item.get("id", ""))

    descriptions = {
        "Count": "Count objects or records.",
        "List": "Return a list of objects or rows.",
        "Lookup": "Find details for one object or a filtered set.",
        "Aggregate": "Compute business metrics such as GMV, net sales, AOV, inventory quantity.",
        "Rank": "Rank objects by a metric.",
        "Compare": "Compare metrics across groups, channels, periods, or entities.",
        "Clarify": "Ask user for missing metric, period, grain, object, or filter.",
        "Unsupported": "Reject unsupported analytical request because data is missing.",
        "Refuse": "Refuse unsafe or destructive requests.",
        "Unknown": "Operation intent not yet classified.",
    }

    operation_intents = []
    for operation, sources in sorted(operation_sources.items()):
        operation_intents.append(
            {
                "operation_intent_id": operation,
                "description": descriptions.get(operation, descriptions["Unknown"]),
                "source_count": len(set(sources)),
                "source_refs": sorted(set(sources))[:20],
                "construction_source": "method_candidates+benchmark_questions",
            }
        )
    return operation_intents


def build_task_slots(method_lookup):
    slot_items = {}
    common_slots = [
        ("target_object", "Target business object or class."),
        ("metric", "Business metric such as GMV, net sales, AOV, count."),
        ("time_period", "Time range or period."),
        ("channel", "Sales channel filter."),
        ("store", "Store filter."),
        ("product", "Product or SKU filter."),
        ("category", "Product category filter."),
        ("brand", "Brand filter."),
        ("customer_segment", "Customer segment filter."),
        ("status", "Status filter."),
        ("limit", "Top-k or row limit."),
        ("order", "Sort direction."),
    ]

    for slot_id, description in common_slots:
        slot_items[slot_id] = {
            "slot_id": slot_id,
            "description": description,
            "source_methods": [],
            "required_by_methods": [],
            "optional_by_methods": [],
            "construction_source": "common_text2sql_slot",
        }

    for method in method_lookup.values():
        method_id = method["method_id"]
        for slot_id in method.get("required_parameters", []):
            slot_items.setdefault(
                slot_id,
                {
                    "slot_id": slot_id,
                    "description": f"Slot inferred from required parameter {slot_id}.",
                    "source_methods": [],
                    "required_by_methods": [],
                    "optional_by_methods": [],
                    "construction_source": "method_required_parameter",
                },
            )
            slot_items[slot_id]["source_methods"].append(method_id)
            slot_items[slot_id]["required_by_methods"].append(method_id)

        for slot_id in method.get("optional_parameters", []):
            slot_items.setdefault(
                slot_id,
                {
                    "slot_id": slot_id,
                    "description": f"Slot inferred from optional parameter {slot_id}.",
                    "source_methods": [],
                    "required_by_methods": [],
                    "optional_by_methods": [],
                    "construction_source": "method_optional_parameter",
                },
            )
            slot_items[slot_id]["source_methods"].append(method_id)
            slot_items[slot_id]["optional_by_methods"].append(method_id)

    for slot in slot_items.values():
        slot["source_methods"] = sorted(set(slot["source_methods"]))
        slot["required_by_methods"] = sorted(set(slot["required_by_methods"]))
        slot["optional_by_methods"] = sorted(set(slot["optional_by_methods"]))

    return sorted(slot_items.values(), key=lambda item: item["slot_id"])


def build_task_values(benchmark_spec):
    values = []
    seed_values = {
        "channel": ["Shopee", "TikTok Shop", "Website", "Offline"],
        "metric": ["GMV", "Net Sales", "AOV", "Order Count", "Inventory Available"],
        "time_period": ["tháng 9/2026", "tháng 8/2026"],
        "expected_action": ["EXECUTE_SQL", "CLARIFY", "REFUSE", "UNSUPPORTED"],
    }
    for value_type, items in seed_values.items():
        for value in items:
            values.append(
                {
                    "value": value,
                    "value_type": value_type,
                    "description": f"Seed task value for {value_type}.",
                    "construction_source": "seed_value",
                }
            )

    for item in benchmark_spec:
        if item.get("method"):
            values.append(
                {
                    "value": item["method"],
                    "value_type": "method_id",
                    "description": f"Method id used by testcase {item.get('id')}.",
                    "construction_source": "benchmark_spec",
                }
            )
    dedup = {}
    for item in values:
        dedup[(item["value_type"], item["value"])] = item
    return list(dedup.values())


def build_task_scenarios(benchmark_spec):
    scenarios = []
    for item in benchmark_spec:
        scenarios.append(
            {
                "scenario_id": item.get("id"),
                "business_intent_id": text_to_id(item.get("group", "Other"), "Intent"),
                "source_group": item.get("group"),
                "scenario": item.get("scenario"),
                "question": item.get("question"),
                "expected_action": item.get("expected_action"),
                "difficulty": item.get("difficulty"),
                "priority": item.get("priority"),
                "method_id": item.get("method"),
                "required_semantics": item.get("required"),
                "forbidden_semantics": item.get("forbidden"),
                "gold_sql": item.get("gold_sql"),
                "construction_source": "benchmark_spec",
            }
        )
    return scenarios


def build_task_examples(task_scenarios, limit=30):
    priority = {"L1": 1, "L2": 2, "L3": 3, "L4": 4, "L5": 5}
    selected = sorted(
        task_scenarios,
        key=lambda item: (
            item.get("expected_action") != "EXECUTE_SQL",
            priority.get(item.get("difficulty"), 99),
            item.get("scenario_id") or "",
        ),
    )[:limit]
    return [
        {
            "question": item["question"],
            "business_intent_id": item["business_intent_id"],
            "expected_action": item["expected_action"],
            "method_id": item["method_id"],
            "difficulty": item["difficulty"],
            "required_semantics": item["required_semantics"],
            "forbidden_semantics": item["forbidden_semantics"],
        }
        for item in selected
    ]


def split_policies(unsupported_scope_candidates):
    clarification = []
    unsupported = []
    for item in unsupported_scope_candidates:
        action = item.get("expected_action")
        if action == "CLARIFY":
            clarification.append(item)
        else:
            unsupported.append(item)
    return clarification, unsupported


BUSINESS_INTENT_ENRICHMENT_CONTRACT = {
    "business_intent_enrichments": [
        {
            "business_intent_id": "same id from input",
            "business_intent_name": "clear Vietnamese/English business name",
            "description": "business meaning",
            "allowed_operation_intents": [],
            "required_slots": [],
            "optional_slots": [],
            "risk_notes": [],
            "confidence": 0.0,
        }
    ]
}


SLOT_POLICY_ENRICHMENT_CONTRACT = {
    "slot_enrichments": [
        {
            "slot_id": "same slot id from input",
            "description": "slot meaning",
            "value_type": "object | metric | time | enum | id | threshold | text | unknown",
            "clarify_if_missing_for_operations": [],
            "confidence": 0.0,
        }
    ],
    "policy_notes": [
        {
            "policy_id": "snake_case_id",
            "description": "important policy for task parsing",
            "applies_to": [],
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
Bạn là business/task ontology architect cho Text2SQL trong môi trường industry.

Nhiệm vụ:
- Đọc context được cung cấp.
- Enrich business intent, slot, và policy để hỗ trợ parse user question.
- Không sinh SQL.
- Không tự tạo method_id hoặc business_intent_id ngoài input.
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


def merge_business_intent_enrichments(business_intents, enrichments):
    by_id = {item.get("business_intent_id"): item for item in enrichments}
    for item in business_intents:
        enrichment = by_id.get(item["business_intent_id"])
        if not enrichment:
            continue
        item["business_intent_name"] = enrichment.get("business_intent_name") or item["business_intent_name"]
        item["description"] = enrichment.get("description") or item["description"]
        item["allowed_operation_intents"] = enrichment.get("allowed_operation_intents", [])
        item["required_slots"] = enrichment.get("required_slots", [])
        item["optional_slots"] = enrichment.get("optional_slots", [])
        item["risk_notes"] = enrichment.get("risk_notes", [])
        item["llm_confidence"] = enrichment.get("confidence")
        item["construction_source"] = "benchmark_group+llm_enrichment"
    return business_intents


def merge_slot_enrichments(task_slots, enrichments):
    by_id = {item.get("slot_id"): item for item in enrichments}
    for item in task_slots:
        enrichment = by_id.get(item["slot_id"])
        if not enrichment:
            continue
        item["description"] = enrichment.get("description") or item["description"]
        item["value_type"] = enrichment.get("value_type", "unknown")
        item["clarify_if_missing_for_operations"] = enrichment.get("clarify_if_missing_for_operations", [])
        item["llm_confidence"] = enrichment.get("confidence")
        item["construction_source"] = item["construction_source"] + "+llm_enrichment"
    return task_slots


def ensure_referenced_slots(task_slots, business_intents):
    existing_slot_ids = {item["slot_id"] for item in task_slots}
    new_slots = []

    for intent in business_intents:
        referenced_slots = intent.get("required_slots", []) + intent.get("optional_slots", [])
        for slot_id in referenced_slots:
            if not slot_id or slot_id in existing_slot_ids:
                continue
            existing_slot_ids.add(slot_id)
            new_slots.append(
                {
                    "slot_id": slot_id,
                    "description": f"Slot referenced by business intent {intent['business_intent_id']}.",
                    "source_methods": [],
                    "required_by_methods": [],
                    "optional_by_methods": [],
                    "value_type": "unknown",
                    "clarify_if_missing_for_operations": [],
                    "construction_source": "llm_business_intent_reference",
                }
            )

    return sorted(task_slots + new_slots, key=lambda item: item["slot_id"])


def build_business_task_ontology(database_id, inventory_dir, object_ontology_dir, output_dir, use_llm, config_path, proxy_mode):
    inventory_dir = Path(inventory_dir)
    object_ontology_dir = Path(object_ontology_dir)
    output_dir = Path(output_dir)

    benchmark_spec = load_json(inventory_dir / "benchmark_spec_snapshot.json")
    database_overview = load_json(inventory_dir / "database_overview.json")
    classes = load_json(object_ontology_dir / "ontology_classes.json")["classes"]
    derived_classes_path = object_ontology_dir / "ontology_derived_classes.json"
    if derived_classes_path.exists():
        derived_classes = load_json(derived_classes_path)["derived_classes"]
    else:
        derived_classes = []
    method_candidates = load_json(object_ontology_dir / "ontology_method_candidates.json")["method_candidates"]
    unsupported_scope_candidates = load_json(object_ontology_dir / "unsupported_scope_candidates.json")["unsupported_scope_candidates"]

    method_lookup = build_method_lookup(method_candidates)
    business_intents = build_business_intents(benchmark_spec, method_lookup)
    operation_intents = build_operation_intents(benchmark_spec, method_lookup)
    task_slots = build_task_slots(method_lookup)
    task_values = build_task_values(benchmark_spec)
    task_scenarios = build_task_scenarios(benchmark_spec)
    task_examples = build_task_examples(task_scenarios)
    clarification_policy, unsupported_policy = split_policies(unsupported_scope_candidates)

    trace = {
        "database_id": database_id,
        "use_llm": use_llm,
        "config_path": str(config_path),
        "proxy_mode": proxy_mode,
        "deterministic_counts": {
            "business_intents": len(business_intents),
            "operation_intents": len(operation_intents),
            "task_slots": len(task_slots),
            "task_values": len(task_values),
            "task_scenarios": len(task_scenarios),
            "task_examples": len(task_examples),
            "clarification_policy": len(clarification_policy),
            "unsupported_policy": len(unsupported_policy),
        },
    }

    policy_notes = []
    if use_llm:
        configure_proxy(proxy_mode)
        class_cards = [
            {
                "class_id": item["class_id"],
                "class_name": item.get("class_name"),
                "business_domain": item.get("business_domain"),
                "description": item.get("description"),
                "ontology_layer": item.get("ontology_layer", "base_class"),
            }
            for item in classes + derived_classes
        ]
        intent_context = {
            "database_id": database_id,
            "database_overview": database_overview,
            "class_cards": class_cards,
            "business_intents": business_intents,
            "operation_intents": operation_intents,
        }
        slot_context = {
            "database_id": database_id,
            "task_slots": task_slots,
            "task_values": task_values[:80],
            "clarification_policy": clarification_policy,
            "unsupported_policy": unsupported_policy,
        }

        intent_output, intent_raw, intent_system, intent_user = call_json_llm(
            task_name="Enrich business intents for task ontology.",
            contract=BUSINESS_INTENT_ENRICHMENT_CONTRACT,
            context=intent_context,
            config_path=config_path,
        )
        slot_output, slot_raw, slot_system, slot_user = call_json_llm(
            task_name="Enrich task slots and task parsing policies.",
            contract=SLOT_POLICY_ENRICHMENT_CONTRACT,
            context=slot_context,
            config_path=config_path,
        )

        business_intents = merge_business_intent_enrichments(
            business_intents,
            intent_output.get("business_intent_enrichments", []),
        )
        task_slots = merge_slot_enrichments(
            task_slots,
            slot_output.get("slot_enrichments", []),
        )
        policy_notes = slot_output.get("policy_notes", [])

        trace["llm"] = {
            "business_intent_enrichment": {
                "raw_output": intent_raw,
                "parsed_output": intent_output,
                "system_prompt": intent_system,
                "user_prompt": intent_user,
            },
            "slot_policy_enrichment": {
                "raw_output": slot_raw,
                "parsed_output": slot_output,
                "system_prompt": slot_system,
                "user_prompt": slot_user,
            },
        }

    task_slots = ensure_referenced_slots(task_slots, business_intents)

    manifest = {
        "database_id": database_id,
        "artifact_type": "business_task_ontology",
        "version": "v01",
        "construction_mode": "hybrid_llm" if use_llm else "deterministic",
        "input_inventory_dir": str(inventory_dir),
        "input_object_ontology_dir": str(object_ontology_dir),
        "output_files": {
            "business_intents": str(output_dir / "business_intents.json"),
            "operation_intents": str(output_dir / "operation_intents.json"),
            "task_slots": str(output_dir / "task_slots.json"),
            "task_values": str(output_dir / "task_values.json"),
            "task_scenarios": str(output_dir / "task_scenarios.json"),
            "task_examples": str(output_dir / "task_examples.json"),
            "task_clarification_policy": str(output_dir / "task_clarification_policy.json"),
            "task_unsupported_policy": str(output_dir / "task_unsupported_policy.json"),
            "task_policy_notes": str(output_dir / "task_policy_notes.json"),
            "task_ontology_trace": str(output_dir / "task_ontology_trace.json"),
        },
        "counts": {
            "business_intents": len(business_intents),
            "operation_intents": len(operation_intents),
            "task_slots": len(task_slots),
            "task_values": len(task_values),
            "task_scenarios": len(task_scenarios),
            "task_examples": len(task_examples),
            "clarification_policy": len(clarification_policy),
            "unsupported_policy": len(unsupported_policy),
            "task_policy_notes": len(policy_notes),
        },
    }

    save_json({"database_id": database_id, "business_intents": business_intents}, output_dir / "business_intents.json")
    save_json({"database_id": database_id, "operation_intents": operation_intents}, output_dir / "operation_intents.json")
    save_json({"database_id": database_id, "task_slots": task_slots}, output_dir / "task_slots.json")
    save_json({"database_id": database_id, "task_values": task_values}, output_dir / "task_values.json")
    save_json({"database_id": database_id, "task_scenarios": task_scenarios}, output_dir / "task_scenarios.json")
    save_json({"database_id": database_id, "task_examples": task_examples}, output_dir / "task_examples.json")
    save_json({"database_id": database_id, "task_clarification_policy": clarification_policy}, output_dir / "task_clarification_policy.json")
    save_json({"database_id": database_id, "task_unsupported_policy": unsupported_policy}, output_dir / "task_unsupported_policy.json")
    save_json({"database_id": database_id, "task_policy_notes": policy_notes}, output_dir / "task_policy_notes.json")
    save_json(trace, output_dir / "task_ontology_trace.json")
    save_json(manifest, output_dir / "task_ontology_manifest.json")
    return manifest


def build_parser():
    parser = argparse.ArgumentParser(
        description="Build business task ontology from benchmark scenarios and object ontology."
    )
    parser.add_argument("--database-id", required=True)
    parser.add_argument("--inventory-dir", required=True)
    parser.add_argument("--object-ontology-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--config-path", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--use-llm", action="store_true")
    parser.add_argument("--proxy-mode", choices=["company", "none"], default="company")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    manifest = build_business_task_ontology(
        database_id=args.database_id,
        inventory_dir=args.inventory_dir,
        object_ontology_dir=args.object_ontology_dir,
        output_dir=args.output_dir,
        use_llm=args.use_llm,
        config_path=Path(args.config_path),
        proxy_mode=args.proxy_mode,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
