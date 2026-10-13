import argparse
import hashlib
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


def normalize_key(value):
    return re.sub(r"[^a-z0-9]+", "_", (value or "").lower()).strip("_")


def stable_policy_id(policy_type, statement, scope):
    raw = f"{policy_type}|{statement}|{scope}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
    prefix = normalize_key(policy_type).upper()
    return f"POLICY_{prefix}_{digest}"


def build_policy(policy_type, statement, enforcement_action, severity, source_type, source_id, applies_to_methods=None):
    applies_to_methods = applies_to_methods or []
    scope = ",".join(sorted(applies_to_methods)) or source_id
    return {
        "policy_id": stable_policy_id(policy_type, statement, scope),
        "policy_type": policy_type,
        "statement": statement,
        "enforcement_action": enforcement_action,
        "severity": severity,
        "applies_to_methods": sorted(set(applies_to_methods)),
        "source": {
            "source_type": source_type,
            "source_id": source_id,
        },
        "audit_question": "",
        "failure_signature": "",
        "confidence": 0.0,
        "construction_source": "deterministic_contract_policy",
    }


def append_policy(policy_items, policy):
    key = (
        policy["policy_type"],
        policy["statement"].strip().lower(),
        policy["enforcement_action"],
        tuple(policy["applies_to_methods"]),
    )
    if key not in policy_items:
        policy_items[key] = policy


def build_method_semantic_policies(method_contracts):
    policy_items = {}

    for contract in method_contracts:
        method_id = contract["method_id"]

        for statement in contract.get("required_semantics", []):
            append_policy(
                policy_items,
                build_policy(
                    policy_type="required_semantic",
                    statement=statement,
                    enforcement_action="require",
                    severity="HIGH",
                    source_type="method_contract.required_semantics",
                    source_id=method_id,
                    applies_to_methods=[method_id],
                ),
            )

        for statement in contract.get("forbidden_semantics", []):
            append_policy(
                policy_items,
                build_policy(
                    policy_type="forbidden_semantic",
                    statement=statement,
                    enforcement_action="block_if_present",
                    severity="HIGH",
                    source_type="method_contract.forbidden_semantics",
                    source_id=method_id,
                    applies_to_methods=[method_id],
                ),
            )

        for statement in contract.get("semantic_guardrails", []):
            append_policy(
                policy_items,
                build_policy(
                    policy_type="semantic_guardrail",
                    statement=statement,
                    enforcement_action="validate",
                    severity="HIGH",
                    source_type="method_contract.semantic_guardrails",
                    source_id=method_id,
                    applies_to_methods=[method_id],
                ),
            )

        for statement in contract.get("common_failure_modes", []):
            append_policy(
                policy_items,
                build_policy(
                    policy_type="known_failure_mode",
                    statement=statement,
                    enforcement_action="flag_for_audit",
                    severity="MEDIUM",
                    source_type="method_contract.common_failure_modes",
                    source_id=method_id,
                    applies_to_methods=[method_id],
                ),
            )

        for statement in contract.get("validation_rules", []):
            append_policy(
                policy_items,
                build_policy(
                    policy_type="runtime_validation_rule",
                    statement=statement,
                    enforcement_action="validate",
                    severity="HIGH",
                    source_type="method_contract.validation_rules",
                    source_id=method_id,
                    applies_to_methods=[method_id],
                ),
            )

    return list(policy_items.values())


def filter_valid_methods(method_ids, valid_method_ids):
    return [
        method_id
        for method_id in method_ids
        if method_id in valid_method_ids
    ]


def build_task_policy_policies(task_policy_notes, clarification_policy, unsupported_policy, valid_method_ids):
    policy_items = {}

    for note in task_policy_notes:
        applies_to = filter_valid_methods(note.get("applies_to", []), valid_method_ids)
        append_policy(
            policy_items,
            build_policy(
                policy_type="task_policy_note",
                statement=note.get("description", ""),
                enforcement_action="validate",
                severity="MEDIUM",
                source_type="task_policy_notes",
                source_id=note.get("policy_id", ""),
                applies_to_methods=applies_to,
            ),
        )

    for item in clarification_policy:
        append_policy(
            policy_items,
            build_policy(
                policy_type="clarification_policy",
                statement=item.get("reason") or item.get("description", ""),
                enforcement_action="ask_clarification",
                severity="HIGH",
                source_type="task_clarification_policy",
                source_id=item.get("scope_id", ""),
                applies_to_methods=[],
            ),
        )

    for item in unsupported_policy:
        expected_action = item.get("expected_action", "UNSUPPORTED")
        enforcement_action = "refuse" if expected_action == "REFUSE" else "reject_unsupported"
        append_policy(
            policy_items,
            build_policy(
                policy_type="unsupported_or_safety_policy",
                statement=item.get("reason") or item.get("description", ""),
                enforcement_action=enforcement_action,
                severity="HIGH",
                source_type="task_unsupported_policy",
                source_id=item.get("scope_id", ""),
                applies_to_methods=[],
            ),
        )

    return list(policy_items.values())


def build_policy_test_candidates(semantic_policies, task_scenarios):
    scenarios_by_method = defaultdict(list)
    for scenario in task_scenarios:
        scenarios_by_method[scenario.get("method_id", "")].append(scenario)

    candidates = []
    for policy in semantic_policies:
        methods = policy.get("applies_to_methods", [])
        source_id = policy["source"]["source_id"]
        related_scenarios = []
        for method_id in methods:
            related_scenarios.extend(scenarios_by_method.get(method_id, [])[:3])

        if not related_scenarios:
            related_scenarios = [
                scenario
                for scenario in task_scenarios
                if scenario.get("scenario_id", "").lower() == source_id
            ]

        candidates.append(
            {
                "policy_id": policy["policy_id"],
                "policy_type": policy["policy_type"],
                "enforcement_action": policy["enforcement_action"],
                "severity": policy["severity"],
                "statement": policy["statement"],
                "test_goal": policy.get("audit_question") or f"Verify policy: {policy['statement']}",
                "related_scenarios": [
                    {
                        "scenario_id": item.get("scenario_id"),
                        "question": item.get("question"),
                        "method_id": item.get("method_id"),
                        "expected_action": item.get("expected_action"),
                        "required_semantics": item.get("required_semantics"),
                        "forbidden_semantics": item.get("forbidden_semantics"),
                    }
                    for item in related_scenarios[:5]
                ],
            }
        )

    return candidates


SEMANTIC_POLICY_ENRICHMENT_CONTRACT = {
    "policy_enrichments": [
        {
            "policy_id": "same policy id from input",
            "normalized_statement": "short precise policy statement",
            "audit_question": "question/check that audit should answer",
            "failure_signature": "what wrong SQL/planning usually looks like",
            "severity": "HIGH | MEDIUM | LOW",
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
Bạn là semantic policy reviewer cho Text2SQL trong môi trường industry.

Nhiệm vụ:
- Đọc danh sách policy đã sinh từ ontology/contract.
- Chuẩn hóa statement, audit question, failure signature.
- Không đổi policy_id.
- Không tạo policy_id mới.
- Không sinh SQL.
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


def batch_items(items, batch_size):
    for start in range(0, len(items), batch_size):
        yield items[start:start + batch_size]


def enrich_policies_with_llm(semantic_policies, config_path, llm_batch_size):
    trace_batches = []
    enrichments = []

    for batch_index, batch in enumerate(batch_items(semantic_policies, llm_batch_size), start=1):
        context = {
            "batch_index": batch_index,
            "semantic_policies": [
                {
                    "policy_id": item["policy_id"],
                    "policy_type": item["policy_type"],
                    "statement": item["statement"],
                    "enforcement_action": item["enforcement_action"],
                    "severity": item["severity"],
                    "applies_to_methods": item["applies_to_methods"],
                }
                for item in batch
            ],
        }
        parsed, raw_output, system_prompt, user_prompt = call_json_llm(
            task_name="Normalize semantic policies for runtime audit.",
            contract=SEMANTIC_POLICY_ENRICHMENT_CONTRACT,
            context=context,
            config_path=config_path,
        )
        enrichments.extend(parsed.get("policy_enrichments", []))
        trace_batches.append(
            {
                "batch_index": batch_index,
                "policy_count": len(batch),
                "raw_output": raw_output,
                "parsed_output": parsed,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
            }
        )

    return enrichments, trace_batches


def merge_policy_enrichments(semantic_policies, enrichments):
    by_id = {item.get("policy_id"): item for item in enrichments}
    for policy in semantic_policies:
        enrichment = by_id.get(policy["policy_id"])
        if not enrichment:
            continue
        policy["normalized_statement"] = enrichment.get("normalized_statement") or policy["statement"]
        policy["audit_question"] = enrichment.get("audit_question", "")
        policy["failure_signature"] = enrichment.get("failure_signature", "")
        policy["severity"] = enrichment.get("severity") or policy["severity"]
        policy["confidence"] = enrichment.get("confidence", 0.0)
        policy["construction_source"] = policy["construction_source"] + "+llm_enrichment"
    return semantic_policies


def audit_semantic_policies(semantic_policies, method_contracts):
    method_ids = {item["method_id"] for item in method_contracts}
    policy_ids = set()
    findings = []

    for policy in semantic_policies:
        policy_id = policy.get("policy_id", "")
        if policy_id in policy_ids:
            findings.append(
                {
                    "severity": "HIGH",
                    "category": "duplicate_policy_id",
                    "policy_id": policy_id,
                    "message": "Duplicate policy_id found.",
                }
            )
        policy_ids.add(policy_id)

        if not policy.get("statement"):
            findings.append(
                {
                    "severity": "HIGH",
                    "category": "empty_policy_statement",
                    "policy_id": policy_id,
                    "message": "Semantic policy has empty statement.",
                }
            )

        for method_id in policy.get("applies_to_methods", []):
            if method_id not in method_ids:
                findings.append(
                    {
                        "severity": "HIGH",
                        "category": "unknown_method_reference",
                        "policy_id": policy_id,
                        "method_id": method_id,
                        "message": "Semantic policy references method_id not found in method contracts.",
                    }
                )

    return findings


def build_semantic_policy_artifacts(
    database_id,
    method_contract_dir,
    task_ontology_dir,
    output_dir,
    use_llm,
    config_path,
    proxy_mode,
    llm_batch_size,
):
    method_contract_dir = Path(method_contract_dir)
    task_ontology_dir = Path(task_ontology_dir)
    output_dir = Path(output_dir)

    method_contracts = load_json(method_contract_dir / "method_contracts.json")["method_contracts"]
    valid_method_ids = {item["method_id"] for item in method_contracts}
    task_scenarios = load_json(task_ontology_dir / "task_scenarios.json")["task_scenarios"]
    task_policy_notes = load_json(task_ontology_dir / "task_policy_notes.json")["task_policy_notes"]
    clarification_policy = load_json(task_ontology_dir / "task_clarification_policy.json")["task_clarification_policy"]
    unsupported_policy = load_json(task_ontology_dir / "task_unsupported_policy.json")["task_unsupported_policy"]

    method_policies = build_method_semantic_policies(method_contracts)
    task_policies = build_task_policy_policies(
        task_policy_notes=task_policy_notes,
        clarification_policy=clarification_policy,
        unsupported_policy=unsupported_policy,
        valid_method_ids=valid_method_ids,
    )
    semantic_policies = sorted(method_policies + task_policies, key=lambda item: item["policy_id"])

    trace = {
        "database_id": database_id,
        "use_llm": use_llm,
        "config_path": str(config_path),
        "proxy_mode": proxy_mode,
        "deterministic_counts": {
            "method_policies": len(method_policies),
            "task_policies": len(task_policies),
            "semantic_policies": len(semantic_policies),
        },
    }

    if use_llm:
        configure_proxy(proxy_mode)
        enrichments, trace_batches = enrich_policies_with_llm(
            semantic_policies=semantic_policies,
            config_path=config_path,
            llm_batch_size=llm_batch_size,
        )
        semantic_policies = merge_policy_enrichments(semantic_policies, enrichments)
        trace["llm"] = {
            "batch_count": len(trace_batches),
            "enrichment_count": len(enrichments),
            "batches": trace_batches,
        }

    policy_test_candidates = build_policy_test_candidates(
        semantic_policies=semantic_policies,
        task_scenarios=task_scenarios,
    )
    audit_findings = audit_semantic_policies(
        semantic_policies=semantic_policies,
        method_contracts=method_contracts,
    )
    severity_counts = Counter(item["severity"] for item in semantic_policies)
    type_counts = Counter(item["policy_type"] for item in semantic_policies)
    action_counts = Counter(item["enforcement_action"] for item in semantic_policies)
    readiness_status = "READY" if not [item for item in audit_findings if item["severity"] == "HIGH"] else "NOT_READY"

    manifest = {
        "database_id": database_id,
        "artifact_type": "semantic_policies",
        "version": "v01",
        "construction_mode": "hybrid_llm" if use_llm else "deterministic",
        "input_method_contract_dir": str(method_contract_dir),
        "input_task_ontology_dir": str(task_ontology_dir),
        "readiness_status": readiness_status,
        "output_files": {
            "semantic_policies": str(output_dir / "semantic_policies.json"),
            "policy_test_candidates": str(output_dir / "policy_test_candidates.json"),
            "semantic_policy_audit": str(output_dir / "semantic_policy_audit.json"),
            "semantic_policy_trace": str(output_dir / "semantic_policy_trace.json"),
        },
        "counts": {
            "semantic_policies": len(semantic_policies),
            "policy_test_candidates": len(policy_test_candidates),
            "audit_findings": len(audit_findings),
            "high_findings": len([item for item in audit_findings if item["severity"] == "HIGH"]),
            "policy_count_by_severity": dict(sorted(severity_counts.items())),
            "policy_count_by_type": dict(sorted(type_counts.items())),
            "policy_count_by_action": dict(sorted(action_counts.items())),
        },
    }

    save_json({"database_id": database_id, "semantic_policies": semantic_policies}, output_dir / "semantic_policies.json")
    save_json({"database_id": database_id, "policy_test_candidates": policy_test_candidates}, output_dir / "policy_test_candidates.json")
    save_json({"database_id": database_id, "audit_findings": audit_findings}, output_dir / "semantic_policy_audit.json")
    save_json(trace, output_dir / "semantic_policy_trace.json")
    save_json(manifest, output_dir / "semantic_policy_manifest.json")
    return manifest


def build_parser():
    parser = argparse.ArgumentParser(
        description="Build semantic policies from method contracts and task ontology policies."
    )
    parser.add_argument("--database-id", required=True)
    parser.add_argument("--method-contract-dir", required=True)
    parser.add_argument("--task-ontology-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--config-path", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--use-llm", action="store_true")
    parser.add_argument("--proxy-mode", choices=["company", "none"], default="company")
    parser.add_argument("--llm-batch-size", type=int, default=10)
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    manifest = build_semantic_policy_artifacts(
        database_id=args.database_id,
        method_contract_dir=args.method_contract_dir,
        task_ontology_dir=args.task_ontology_dir,
        output_dir=args.output_dir,
        use_llm=args.use_llm,
        config_path=Path(args.config_path),
        proxy_mode=args.proxy_mode,
        llm_batch_size=args.llm_batch_size,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
