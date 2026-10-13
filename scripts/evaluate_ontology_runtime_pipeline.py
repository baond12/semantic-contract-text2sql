import argparse
import csv
import importlib.util
import hashlib
import json
import os
import re
import sqlite3
import time
import traceback
from collections import Counter, defaultdict
from pathlib import Path


DEFAULT_CONFIG_PATH = Path("/home/baond12/Documents/Research_Cadshouse_Analytics/benchmarks_baond_exp/file_for_pipeline_from_scratch/llm-service-dev-text2sql/text2sql_q3_demo/llm_config.yaml")
COMPANY_PROXY_URL = "http://proxy.hcm.fpt.vn:80"


TASK_STATE_CONTRACT = {
    "expected_action": "EXECUTE_SQL | CLARIFY | REFUSE | UNSUPPORTED | UNKNOWN",
    "business_intent_id": "candidate business intent id or UNKNOWN",
    "operation_intent": "candidate operation intent id or UNKNOWN",
    "method_id": "candidate method id or M_NON_SQL or UNKNOWN",
    "slots": [
        {
            "slot_id": "slot id",
            "value": "value extracted from user question",
            "value_type": "time | threshold | enum | id | metric | text | unknown",
            "evidence": "short phrase from user question",
        }
    ],
    "target_classes": [],
    "policy_ids": [],
    "confidence": 0.0,
    "reasoning_summary": "short explanation, no hidden chain-of-thought",
}


SQL_GENERATION_CONTRACT = {
    "sql": "single read-only SQLite SELECT statement",
    "used_tables": [],
    "used_columns": [],
    "preserved_slots": [],
    "applied_policies": [],
    "explanation": "short explanation",
}


SQL_REPAIR_CONTRACT = {
    "status": "OK | REPAIRED | BLOCKED",
    "violations": [],
    "sql": "single read-only SQLite SELECT statement, empty when BLOCKED",
    "used_tables": [],
    "used_columns": [],
    "preserved_slots": [],
    "applied_policies": [],
    "explanation": "short explanation",
}


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


def tokenize(text):
    text = (text or "").lower()
    return [token for token in re.findall(r"[\w]+", text, flags=re.UNICODE) if len(token) > 1]


def bm25_score(query_tokens, document, doc_freq, document_count, avg_doc_len, k1, b):
    score = 0.0
    term_freq = document["term_freq"]
    doc_len = document["doc_len"]
    for token in query_tokens:
        if token not in term_freq:
            continue
        df = doc_freq.get(token, 0)
        idf = math_log(1 + (document_count - df + 0.5) / (df + 0.5))
        tf = term_freq[token]
        denominator = tf + k1 * (1 - b + b * doc_len / max(avg_doc_len, 1e-9))
        score += idf * (tf * (k1 + 1)) / denominator
    return score


def math_log(value):
    import math
    return math.log(value)


def search_bm25(question, cards_by_id, bm25_index, top_k):
    query_tokens = tokenize(question)
    scored = []
    for document in bm25_index["documents"]:
        score = bm25_score(
            query_tokens=query_tokens,
            document=document,
            doc_freq=bm25_index["doc_freq"],
            document_count=bm25_index["document_count"],
            avg_doc_len=bm25_index["avg_doc_len"],
            k1=bm25_index["k1"],
            b=bm25_index["b"],
        )
        if score <= 0:
            continue
        card = cards_by_id[document["card_id"]]
        scored.append(
            {
                "card_id": card["card_id"],
                "card_type": card["card_type"],
                "title": card["title"],
                "score": round(score, 6),
                "metadata": card["metadata"],
                "text": card["text"],
            }
        )
    return sorted(scored, key=lambda item: item["score"], reverse=True)[:top_k]


def group_candidates(candidates, per_type_limit):
    grouped = defaultdict(list)
    for item in candidates:
        grouped[item["card_type"]].append(item)
    return {
        card_type: items[:per_type_limit]
        for card_type, items in sorted(grouped.items())
    }


def compact_candidates(grouped_candidates):
    compact = {}
    for card_type, items in grouped_candidates.items():
        compact[card_type] = [
            {
                "card_id": item["card_id"],
                "title": item["title"],
                "score": item["score"],
                "metadata": item["metadata"],
                "text": item["text"][:1500],
            }
            for item in items
        ]
    return compact


def extract_json_object(text):
    start = text.find("{")
    end = text.rfind("}") + 1
    if start < 0 or end <= start:
        raise ValueError("LLM output does not contain JSON object.")
    return json.loads(text[start:end])


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


def parse_task_state(question, candidates, config_path):
    system_prompt = """
Bạn là ontology grounding parser cho Text2SQL.

Nhiệm vụ:
- Map user question vào candidate ontology cards đã retrieve.
- Chỉ chọn business_intent_id, operation_intent, method_id, slot_id, class_id, policy_id có trong candidates.
- Nếu câu hỏi cần hỏi lại, từ chối, hoặc unsupported thì expected_action phải là CLARIFY/REFUSE/UNSUPPORTED.
- Không sinh SQL ở bước này.
- Trả về JSON đúng contract.
- Không giải thích ngoài JSON.
"""
    user_prompt = f"""
USER QUESTION:
{question}

CONTRACT:
{json.dumps(TASK_STATE_CONTRACT, ensure_ascii=False, indent=2)}

CANDIDATE ONTOLOGY CONTEXT:
{json.dumps(candidates, ensure_ascii=False, indent=2)}

Return only JSON.
"""
    raw_output = call_llm(system_prompt, user_prompt, config_path)
    parsed = extract_json_object(raw_output)
    return parsed, raw_output


def build_artifact_indexes(root):
    root = Path(root)
    object_dir = root / "02_object_ontology"
    task_dir = root / "03_business_task_ontology"
    method_dir = root / "04_method_contracts"
    policy_dir = root / "05_semantic_policies"
    retrieval_dir = root / "06_retrieval_indexes"
    benchmark_dir = root / "07_benchmark_cases"

    artifacts = {
        "columns": load_json(root / "01_database_inventory" / "columns.json"),
        "sample_values": load_json(root / "01_database_inventory" / "sample_values.json"),
        "classes": load_json(object_dir / "ontology_classes.json")["classes"],
        "properties": load_json(object_dir / "ontology_properties.json")["properties"],
        "relations": load_json(object_dir / "ontology_relations.json")["relations"],
        "business_intents": load_json(task_dir / "business_intents.json")["business_intents"],
        "operation_intents": load_json(task_dir / "operation_intents.json")["operation_intents"],
        "task_slots": load_json(task_dir / "task_slots.json")["task_slots"],
        "task_values": load_json(task_dir / "task_values.json")["task_values"],
        "method_contracts": load_json(method_dir / "method_contracts.json")["method_contracts"],
        "semantic_policies": load_json(policy_dir / "semantic_policies.json")["semantic_policies"],
        "retrieval_cards": load_json(retrieval_dir / "retrieval_cards.json")["retrieval_cards"],
        "bm25_index": load_json(retrieval_dir / "bm25_index.json")["bm25_index"],
        "benchmark_cases": load_json(benchmark_dir / "benchmark_cases.json")["benchmark_cases"],
    }
    artifacts["by_id"] = {
        "class": {item["class_id"]: item for item in artifacts["classes"]},
        "property": {item["property_id"]: item for item in artifacts["properties"]},
        "relation": {item["relation_id"]: item for item in artifacts["relations"]},
        "business_intent": {item["business_intent_id"]: item for item in artifacts["business_intents"]},
        "operation_intent": {item["operation_intent_id"]: item for item in artifacts["operation_intents"]},
        "task_slot": {item["slot_id"]: item for item in artifacts["task_slots"]},
        "method": {item["method_id"]: item for item in artifacts["method_contracts"]},
        "semantic_policy": {item["policy_id"]: item for item in artifacts["semantic_policies"]},
        "card": {item["card_id"]: item for item in artifacts["retrieval_cards"]},
    }
    return artifacts


def slot_values(task_state):
    return {
        item.get("slot_id"): item.get("value")
        for item in task_state.get("slots", [])
        if item.get("slot_id")
    }


SOFT_REQUIRED_SLOT_IDS = {"filter_criteria", "metric", "segment_criteria"}


def validate_task_state(task_state, artifacts):
    action = task_state.get("expected_action", "UNKNOWN")
    method_id = task_state.get("method_id", "UNKNOWN")
    business_intent_id = task_state.get("business_intent_id", "UNKNOWN")
    method = artifacts["by_id"]["method"].get(method_id)
    business_intent = artifacts["by_id"]["business_intent"].get(business_intent_id)
    validation = {
        "decision": "BLOCK_CONTRACT_VIOLATION",
        "reason": "",
        "missing_required_slots": [],
        "matched_policy_ids": [],
        "method_contract": method,
    }

    if action in ["CLARIFY", "REFUSE", "UNSUPPORTED"]:
        validation["decision"] = {
            "CLARIFY": "ASK_CLARIFICATION",
            "REFUSE": "REFUSE",
            "UNSUPPORTED": "UNSUPPORTED",
        }[action]
        validation["reason"] = f"Task parser selected non-SQL action: {action}."
        return validation

    if action != "EXECUTE_SQL":
        validation["reason"] = f"Unknown or unsupported expected_action: {action}."
        return validation

    if not method:
        validation["reason"] = f"Unknown method_id: {method_id}."
        return validation

    if business_intent and method_id not in business_intent.get("allowed_methods", []):
        validation["reason"] = f"Method {method_id} is not allowed by business intent {business_intent_id}."
        return validation

    values = slot_values(task_state)
    missing_slots = [
        slot["slot_id"]
        for slot in method.get("required_slots", [])
        if slot["slot_id"] not in SOFT_REQUIRED_SLOT_IDS
        and (slot["slot_id"] not in values or values.get(slot["slot_id"]) in ["", None])
    ]
    if missing_slots:
        validation["decision"] = "ASK_CLARIFICATION"
        validation["reason"] = "Missing required slots."
        validation["missing_required_slots"] = missing_slots
        return validation

    policy_ids = [
        policy["policy_id"]
        for policy in artifacts["semantic_policies"]
        if method_id in policy.get("applies_to_methods", [])
    ]
    validation["decision"] = "ALLOW_EXECUTE_SQL"
    validation["reason"] = "Task state satisfies ontology and method contract."
    validation["matched_policy_ids"] = policy_ids
    return validation


def compact_sample_values(artifacts, column_ids, max_values_per_column):
    sample_by_column = {
        item["column_id"]: item.get("sample_values", [])
        for item in artifacts.get("sample_values", [])
    }
    hints = []
    for column_id in column_ids:
        values = sample_by_column.get(column_id, [])[:max_values_per_column]
        if values:
            hints.append(
                {
                    "column_id": column_id,
                    "sample_values": values,
                }
            )
    return hints


def build_semantic_value_rules(artifacts, method):
    sample_by_column = {
        item["column_id"]: [value["value"] for value in item.get("sample_values", [])]
        for item in artifacts.get("sample_values", [])
    }
    rules = []
    semantic_text = " ".join(
        str(item)
        for item in [
            method.get("business_meaning", ""),
            *method.get("required_semantics", []),
            *method.get("semantic_guardrails", []),
            *method.get("forbidden_semantics", []),
            *method.get("common_failure_modes", []),
        ]
    ).lower()

    order_status_values = sample_by_column.get("orders.status", [])
    paid_order_values = [value for value in ["paid", "shipped", "delivered"] if value in order_status_values]
    if paid_order_values and ("paid" in semantic_text or "thanh toán" in semantic_text):
        rules.append(
            {
                "rule_id": "paid_order_status_values",
                "column_id": "orders.status",
                "business_meaning": "Paid/valid orders include statuses after successful payment, not only literal status='paid'.",
                "allowed_values": paid_order_values,
            }
        )

    payment_status_values = sample_by_column.get("payments.status", [])
    if "success" in payment_status_values and ("success" in semantic_text or "thành công" in semantic_text or "thanh toán" in semantic_text):
        rules.append(
            {
                "rule_id": "successful_payment_status_value",
                "column_id": "payments.status",
                "business_meaning": "Successful payment must use payments.status='success'.",
                "allowed_values": ["success"],
            }
        )

    return rules


def build_sql_context(task_state, validation, artifacts, example_limit):
    method = validation["method_contract"]
    policy_by_id = artifacts["by_id"]["semantic_policy"]
    relation_by_id = artifacts["by_id"]["relation"]
    property_by_id = artifacts["by_id"]["property"]
    related_policy_ids = validation.get("matched_policy_ids", [])[:80]
    example_scenarios = method.get("example_scenarios", [])[:example_limit]

    return {
        "task_state": task_state,
        "method_contract": {
            "method_id": method["method_id"],
            "business_meaning": method.get("business_meaning"),
            "operation_intent": method.get("operation_intent"),
            "target_classes": method.get("target_classes", []),
            "required_tables": method.get("required_tables", []),
            "required_columns": method.get("required_columns", []),
            "required_slots": method.get("required_slots", []),
            "optional_slots": method.get("optional_slots", []),
            "required_semantics": method.get("required_semantics", []),
            "forbidden_semantics": method.get("forbidden_semantics", []),
            "semantic_guardrails": method.get("semantic_guardrails", []),
            "common_failure_modes": method.get("common_failure_modes", []),
            "observed_sql_features": method.get("observed_sql_features", []),
        },
        "allowed_properties": [
            property_by_id[property_id]
            for property_id in method.get("required_properties", [])
            if property_id in property_by_id
        ],
        "required_relations": [
            relation_by_id[item["relation_id"]]
            for item in method.get("required_relations", [])
            if item.get("relation_id") in relation_by_id
        ],
        "semantic_policies": [
            policy_by_id[policy_id]
            for policy_id in related_policy_ids
            if policy_id in policy_by_id
        ],
        "database_value_hints": compact_sample_values(
            artifacts=artifacts,
            column_ids=method.get("required_columns", []),
            max_values_per_column=12,
        ),
        "semantic_value_rules": build_semantic_value_rules(
            artifacts=artifacts,
            method=method,
        ),
        "few_shot_examples": example_scenarios,
    }


def generate_sql(question, sql_context, config_path):
    system_prompt = """
Bạn là SQL generator có kiểm soát bằng ontology cho SQLite.

Quy tắc bắt buộc:
- Chỉ sinh một câu SELECT/ WITH read-only SQLite.
- Chỉ dùng bảng/cột/relation trong SQL_CONTEXT.
- Nếu cần lọc bằng giá trị enum/text, phải dùng literal đúng theo database_value_hints.
- Nếu SQL_CONTEXT có semantic_value_rules thì phải dùng đúng allowed_values trong rule đó.
- Nếu câu hỏi có tháng/năm, ưu tiên dùng khoảng ngày dạng >= 'YYYY-MM-01' và < 'YYYY-MM-next-01'.
- Phải bảo toàn required slots, required semantics và semantic guardrails.
- Không vi phạm forbidden semantics.
- Nếu context không đủ, trả sql rỗng và giải thích ngắn trong JSON.
- Trả về JSON đúng contract, không giải thích ngoài JSON.
"""
    user_prompt = f"""
USER QUESTION:
{question}

CONTRACT:
{json.dumps(SQL_GENERATION_CONTRACT, ensure_ascii=False, indent=2)}

SQL_CONTEXT:
{json.dumps(sql_context, ensure_ascii=False, indent=2)}

Return only JSON.
"""
    raw_output = call_llm(system_prompt, user_prompt, config_path)
    parsed = extract_json_object(raw_output)
    return parsed, raw_output


def verify_and_repair_sql(question, sql_context, sql_output, config_path):
    system_prompt = """
Bạn là SQL semantic contract verifier cho SQLite.

Nhiệm vụ:
- Kiểm tra SQL đã bảo toàn đầy đủ method_contract, required_slots, required_semantics, semantic_guardrails, forbidden_semantics và database_value_hints chưa.
- Nếu SQL_CONTEXT có deterministic_sql_contract_audit thì phải sửa tất cả violations trong đó.
- Nếu SQL_CONTEXT có semantic_value_rules thì phải dùng đúng allowed_values trong rule đó.
- Nếu SQL đã đúng, trả status=OK và giữ nguyên SQL.
- Nếu SQL thiếu/sai nhưng sửa được trong phạm vi SQL_CONTEXT, trả status=REPAIRED và SQL đã sửa.
- Nếu context không đủ hoặc SQL cần dùng bảng/cột ngoài contract, trả status=BLOCKED và sql rỗng.
- Không sinh giải thích ngoài JSON.
"""
    user_prompt = f"""
USER QUESTION:
{question}

CONTRACT:
{json.dumps(SQL_REPAIR_CONTRACT, ensure_ascii=False, indent=2)}

SQL_CONTEXT:
{json.dumps(sql_context, ensure_ascii=False, indent=2)}

SQL_OUTPUT_TO_VERIFY:
{json.dumps(sql_output, ensure_ascii=False, indent=2)}

Return only JSON.
"""
    raw_output = call_llm(system_prompt, user_prompt, config_path)
    parsed = extract_json_object(raw_output)
    return parsed, raw_output


def extract_table_aliases(sql):
    aliases = {}
    for table, alias in re.findall(r"\b(?:from|join)\s+([a-zA-Z_][\w]*)\s+(?:as\s+)?([a-zA-Z_][\w]*)", sql or "", flags=re.IGNORECASE):
        if alias.lower() not in ["on", "where", "join", "group", "order", "limit"]:
            aliases[table] = alias
    return aliases


def column_ref_present(sql, column_id):
    table, column = column_id.split(".", 1)
    aliases = extract_table_aliases(sql)
    candidates = [f"{table}.{column}", f'"{table}"."{column}"']
    if table in aliases:
        candidates.append(f"{aliases[table]}.{column}")
    normalized = (sql or "").lower()
    return any(candidate.lower() in normalized for candidate in candidates)


def audit_sql_against_semantic_contract(sql_context, sql_output):
    sql = sql_output.get("sql", "")
    method = sql_context["method_contract"]
    semantic_text = " ".join(
        str(item)
        for item in [
            method.get("business_meaning", ""),
            *method.get("required_semantics", []),
            *method.get("semantic_guardrails", []),
            *method.get("forbidden_semantics", []),
            *method.get("common_failure_modes", []),
        ]
    ).lower()
    lower_sql = sql.lower()
    violations = []

    if not is_read_only_select(sql):
        violations.append("SQL must be a single read-only SELECT/WITH statement.")

    if ("paid" in semantic_text or "thanh toán" in semantic_text) and "orders.status" in method.get("required_columns", []):
        if not column_ref_present(sql, "orders.status"):
            violations.append("Missing order status filter required by paid-order semantics: orders.status.")

    if ("success" in semantic_text or "thành công" in semantic_text) and "payments.status" in method.get("required_columns", []):
        if not column_ref_present(sql, "payments.status"):
            violations.append("Missing successful payment filter required by payment semantics: payments.status.")

    if "shipping" in semantic_text and "payment.amount" in lower_sql:
        violations.append("Potential forbidden semantic: payment.amount may include shipping fee.")

    for rule in sql_context.get("semantic_value_rules", []):
        if rule["column_id"] == "orders.status" and column_ref_present(sql, "orders.status"):
            missing_values = [value for value in rule.get("allowed_values", []) if repr(value).lower() not in lower_sql and f'"{value}"'.lower() not in lower_sql]
            if missing_values:
                violations.append(f"Missing paid order status values for orders.status: {missing_values}.")
        if rule["column_id"] == "payments.status" and column_ref_present(sql, "payments.status"):
            missing_values = [value for value in rule.get("allowed_values", []) if repr(value).lower() not in lower_sql and f'"{value}"'.lower() not in lower_sql]
            if missing_values:
                violations.append(f"Missing successful payment status values for payments.status: {missing_values}.")

    if "distinct sku pairs" in semantic_text or "sku_a < sku_b" in semantic_text:
        if "order_items" not in lower_sql or "product_id" not in lower_sql or not re.search(r"product_id\s*[<>]\s*", lower_sql):
            violations.append("Missing distinct SKU pair self-join condition on product_id.")

    for slot in method.get("required_slots", []):
        slot_id = slot["slot_id"]
        if slot_id == "top_n" and "limit" not in lower_sql:
            violations.append("Missing LIMIT for top_n slot.")
        if slot_id == "time_period" and not ("ordered_at" in lower_sql or "created_at" in lower_sql or "snapshot_date" in lower_sql):
            violations.append("Missing time column filter for time_period slot.")

    return {
        "status": "PASS" if not violations else "FAIL",
        "violations": violations,
    }


def normalize_sql(sql):
    return " ".join((sql or "").strip().rstrip(";").split())


def is_read_only_select(sql):
    normalized = normalize_sql(sql).lower()
    if not normalized:
        return False
    if normalized.startswith("select ") or normalized.startswith("with "):
        blocked = [" insert ", " update ", " delete ", " drop ", " alter ", " create ", " replace "]
        return not any(token in f" {normalized} " for token in blocked)
    return False


def execute_sql(sqlite_path, sql):
    connection = sqlite3.connect(sqlite_path)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(sql).fetchall()
    connection.close()
    return [dict(row) for row in rows]


def result_hash(records):
    payload = json.dumps(records, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def result_value_hash(records):
    values = [list(record.values()) for record in records]
    payload = json.dumps(values, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def run_runtime_pipeline(question, artifacts, config_path, sqlite_path, top_k, per_type_limit, example_limit, execute_sql_flag):
    steps = []
    start = time.perf_counter()
    cards_by_id = artifacts["by_id"]["card"]

    candidates = search_bm25(
        question=question,
        cards_by_id=cards_by_id,
        bm25_index=artifacts["bm25_index"],
        top_k=top_k,
    )
    grouped_candidates = group_candidates(candidates, per_type_limit)
    steps.append({"step": "retrieve_candidates", "elapsed_sec": round(time.perf_counter() - start, 4), "candidate_count": len(candidates)})

    step_start = time.perf_counter()
    compact_context = compact_candidates(grouped_candidates)
    task_state, task_raw = parse_task_state(question, compact_context, config_path)
    steps.append({"step": "ontology_grounding_task_state", "elapsed_sec": round(time.perf_counter() - step_start, 4)})

    step_start = time.perf_counter()
    validation = validate_task_state(task_state, artifacts)
    steps.append({"step": "ontology_reasoning_semantic_guard", "elapsed_sec": round(time.perf_counter() - step_start, 4), "decision": validation["decision"]})

    sql_context = None
    sql_output = None
    sql_verification = None
    sql_contract_audit = None
    sql_raw = ""
    sql_verify_raw = ""
    records = []
    execution_error = ""

    if validation["decision"] == "ALLOW_EXECUTE_SQL":
        step_start = time.perf_counter()
        sql_context = build_sql_context(task_state, validation, artifacts, example_limit)
        steps.append({"step": "build_sql_context", "elapsed_sec": round(time.perf_counter() - step_start, 4)})

        step_start = time.perf_counter()
        sql_output, sql_raw = generate_sql(question, sql_context, config_path)
        steps.append({"step": "generate_sql", "elapsed_sec": round(time.perf_counter() - step_start, 4)})

        step_start = time.perf_counter()
        sql_verification, sql_verify_raw = verify_and_repair_sql(question, sql_context, sql_output, config_path)
        steps.append(
            {
                "step": "verify_repair_sql_contract",
                "elapsed_sec": round(time.perf_counter() - step_start, 4),
                "status": sql_verification.get("status"),
                "violation_count": len(sql_verification.get("violations", [])),
            }
        )
        if sql_verification.get("status") in ["OK", "REPAIRED"]:
            sql_output = {
                **sql_output,
                **sql_verification,
            }

        sql_contract_audit = audit_sql_against_semantic_contract(sql_context, sql_output)
        if sql_contract_audit["status"] == "FAIL":
            step_start = time.perf_counter()
            repair_context = {
                **sql_context,
                "deterministic_sql_contract_audit": sql_contract_audit,
            }
            sql_verification, sql_verify_raw = verify_and_repair_sql(question, repair_context, sql_output, config_path)
            steps.append(
                {
                    "step": "repair_sql_from_deterministic_contract_audit",
                    "elapsed_sec": round(time.perf_counter() - step_start, 4),
                    "status": sql_verification.get("status"),
                    "input_violation_count": len(sql_contract_audit["violations"]),
                }
            )
            if sql_verification.get("status") in ["OK", "REPAIRED"]:
                sql_output = {
                    **sql_output,
                    **sql_verification,
                }
            sql_contract_audit = audit_sql_against_semantic_contract(sql_context, sql_output)

        if execute_sql_flag and sql_contract_audit["status"] == "PASS" and is_read_only_select(sql_output.get("sql", "")):
            step_start = time.perf_counter()
            records = execute_sql(sqlite_path, sql_output["sql"])
            steps.append({"step": "execute_sql", "elapsed_sec": round(time.perf_counter() - step_start, 4), "row_count": len(records)})
        elif execute_sql_flag:
            execution_error = "SQL contract audit failed before execution."

    return {
        "question": question,
        "retrieved_candidates": grouped_candidates,
        "task_state": task_state,
        "validation": {
            key: value
            for key, value in validation.items()
            if key != "method_contract"
        },
        "sql_context": sql_context,
        "sql_output": sql_output,
        "sql_verification": sql_verification,
        "sql_contract_audit": sql_contract_audit,
        "records": records,
        "record_hash": result_hash(records) if records else "",
        "record_value_hash": result_value_hash(records) if records else "",
        "execution_error": execution_error,
        "steps": steps,
        "llm_raw": {
            "task_state": task_raw,
            "sql_generation": sql_raw,
            "sql_verification": sql_verify_raw,
        },
        "total_elapsed_sec": round(time.perf_counter() - start, 4),
    }


def build_pipeline_exception_output(question, error):
    return {
        "question": question,
        "retrieved_candidates": {},
        "task_state": {},
        "validation": {
            "decision": "PIPELINE_EXCEPTION",
            "reason": str(error),
        },
        "sql_context": None,
        "sql_output": None,
        "sql_verification": None,
        "sql_contract_audit": None,
        "records": [],
        "record_hash": "",
        "record_value_hash": "",
        "execution_error": str(error),
        "steps": [
            {
                "step": "pipeline_exception",
                "error_type": type(error).__name__,
                "error_message": str(error),
            }
        ],
        "llm_raw": {},
        "traceback": traceback.format_exc(),
        "total_elapsed_sec": 0.0,
    }


def evaluate_cases(cases, artifacts, config_path, sqlite_path, limit, case_ids, top_k, per_type_limit, example_limit, execute_sql_flag, output_dir=None):
    selected = cases
    if case_ids:
        allowed = set(case_ids)
        selected = [item for item in selected if item["case_id"] in allowed]
    if limit:
        selected = selected[:limit]

    results = []
    for index, case in enumerate(selected, start=1):
        print("=" * 100, flush=True)
        print(index, "/", len(selected), case["case_id"], case["difficulty"], case["expected_action"], flush=True)
        print(case["question"], flush=True)
        try:
            output = run_runtime_pipeline(
                question=case["question"],
                artifacts=artifacts,
                config_path=config_path,
                sqlite_path=sqlite_path,
                top_k=top_k,
                per_type_limit=per_type_limit,
                example_limit=example_limit,
                execute_sql_flag=execute_sql_flag,
            )
        except Exception as error:
            output = build_pipeline_exception_output(case["question"], error)
        metrics = score_case(case, output, sqlite_path)
        print("decision:", output["validation"]["decision"], flush=True)
        print("method:", output["task_state"].get("method_id"), "| expected:", case["expected_method_id"], flush=True)
        print("action:", output["task_state"].get("expected_action"), "| expected:", case["expected_action"], flush=True)
        print("case_pass:", metrics["case_pass"], flush=True)
        results.append({"case": case, "output": output, "metrics": metrics})
        if output_dir:
            save_json({"results": results}, Path(output_dir) / "runtime_eval_checkpoint.json")
            save_csv(flatten_results(results), Path(output_dir) / "runtime_eval_checkpoint.csv")
    return results


def expected_value_hash(case, sqlite_path):
    cached = case["expected_result"].get("result_value_sha256")
    if cached:
        return cached

    preview = case["expected_result"].get("result_preview") or []
    expected_row_count = case["expected_result"].get("expected_row_count")
    if expected_row_count == len(preview):
        return result_value_hash(preview)

    gold_sql = case.get("gold_sql", "")
    if sqlite_path and gold_sql:
        return result_value_hash(execute_sql(sqlite_path, gold_sql))

    return ""


def score_case(case, output, sqlite_path=None):
    expected_action = case["expected_action"]
    task_state = output["task_state"]
    validation = output["validation"]
    sql_output = output.get("sql_output") or {}
    sql_contract_audit = output.get("sql_contract_audit") or {"status": "PASS"}

    action_match = task_state.get("expected_action") == expected_action
    method_match = True
    if expected_action == "EXECUTE_SQL":
        method_match = task_state.get("method_id") == case["expected_method_id"]

    non_sql_blocked = True
    if expected_action != "EXECUTE_SQL":
        non_sql_blocked = validation["decision"] in ["ASK_CLARIFICATION", "REFUSE", "UNSUPPORTED"]

    sql_generated = bool(sql_output.get("sql")) if expected_action == "EXECUTE_SQL" else not bool(sql_output.get("sql"))
    result_hash_match = True
    result_value_hash_match = True
    if expected_action == "EXECUTE_SQL" and output.get("record_hash"):
        result_hash_match = output["record_hash"] == case["expected_result"].get("result_sha256")
        result_value_hash_match = output["record_value_hash"] == expected_value_hash(case, sqlite_path)

    sql_contract_preserved = True
    if expected_action == "EXECUTE_SQL":
        sql_contract_preserved = sql_contract_audit.get("status") == "PASS"

    return {
        "action_match": action_match,
        "method_match": method_match,
        "non_sql_blocked": non_sql_blocked,
        "sql_generated": sql_generated,
        "sql_contract_preserved": sql_contract_preserved,
        "result_hash_match": result_hash_match,
        "result_value_hash_match": result_value_hash_match,
        "case_pass": action_match and method_match and non_sql_blocked and sql_generated and sql_contract_preserved and (result_hash_match or result_value_hash_match),
    }


def summarize_results(results):
    metrics = [item["metrics"] for item in results]
    total = len(metrics)
    return {
        "case_count": total,
        "case_pass": sum(1 for item in metrics if item["case_pass"]),
        "case_pass_rate": round(sum(1 for item in metrics if item["case_pass"]) / max(1, total), 4),
        "action_accuracy": round(sum(1 for item in metrics if item["action_match"]) / max(1, total), 4),
        "method_accuracy": round(sum(1 for item in metrics if item["method_match"]) / max(1, total), 4),
        "non_sql_block_accuracy": round(sum(1 for item in metrics if item["non_sql_blocked"]) / max(1, total), 4),
        "sql_generation_accuracy": round(sum(1 for item in metrics if item["sql_generated"]) / max(1, total), 4),
        "sql_contract_preservation_accuracy": round(sum(1 for item in metrics if item["sql_contract_preserved"]) / max(1, total), 4),
        "result_hash_accuracy": round(sum(1 for item in metrics if item["result_hash_match"]) / max(1, total), 4),
        "result_value_hash_accuracy": round(sum(1 for item in metrics if item["result_value_hash_match"]) / max(1, total), 4),
    }


def flatten_results(results):
    rows = []
    for item in results:
        case = item["case"]
        output = item["output"]
        metrics = item["metrics"]
        sql_output = output.get("sql_output") or {}
        sql_contract_audit = output.get("sql_contract_audit") or {}
        rows.append(
            {
                "case_id": case["case_id"],
                "difficulty": case["difficulty"],
                "group": case["group"],
                "question": case["question"],
                "expected_action": case["expected_action"],
                "pred_action": output["task_state"].get("expected_action"),
                "expected_method_id": case["expected_method_id"],
                "pred_method_id": output["task_state"].get("method_id"),
                "decision": output["validation"]["decision"],
                "sql_pred": sql_output.get("sql", ""),
                "record_hash": output.get("record_hash", ""),
                "record_value_hash": output.get("record_value_hash", ""),
                "expected_hash": case["expected_result"].get("result_sha256", ""),
                "expected_value_hash": case["expected_result"].get("result_value_sha256", ""),
                "sql_contract_audit_status": sql_contract_audit.get("status", ""),
                "sql_contract_audit_violations": json.dumps(sql_contract_audit.get("violations", []), ensure_ascii=False),
                **metrics,
                "total_elapsed_sec": output["total_elapsed_sec"],
            }
        )
    return rows


def save_eval_outputs(results, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = flatten_results(results)
    summary = summarize_results(results)
    save_json({"summary": summary, "rows": rows}, output_dir / "runtime_eval_summary.json")
    save_json({"results": results}, output_dir / "runtime_eval_results.json")
    save_csv(rows, output_dir / "runtime_eval_results.csv")
    if importlib.util.find_spec("pandas"):
        import pandas as pd
        pd.DataFrame(rows).to_excel(output_dir / "runtime_eval_results.xlsx", index=False)
    return summary


def save_csv(rows, path):
    path = Path(path)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def build_parser():
    parser = argparse.ArgumentParser(description="Evaluate ontology-driven runtime pipeline.")
    parser.add_argument("--offline-root", required=True)
    parser.add_argument("--sqlite-path", required=True)
    parser.add_argument("--config-path", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--top-k", type=int, default=80)
    parser.add_argument("--per-type-limit", type=int, default=12)
    parser.add_argument("--example-limit", type=int, default=3)
    parser.add_argument("--execute-sql", action="store_true")
    parser.add_argument("--proxy-mode", choices=["company", "none"], default="none")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    configure_proxy(args.proxy_mode)

    artifacts = build_artifact_indexes(args.offline_root)
    results = evaluate_cases(
        cases=artifacts["benchmark_cases"],
        artifacts=artifacts,
        config_path=Path(args.config_path),
        sqlite_path=Path(args.sqlite_path),
        limit=args.limit,
        case_ids=args.case_id,
        top_k=args.top_k,
        per_type_limit=args.per_type_limit,
        example_limit=args.example_limit,
        execute_sql_flag=args.execute_sql,
        output_dir=Path(args.output_dir),
    )
    summary = save_eval_outputs(results, args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
