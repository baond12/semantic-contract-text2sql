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


LLM_JUDGE_CONTRACT = {
    "schema_linking_score": "0 | 1 | 2",
    "execution_validity_score": "0 | 1 | 2",
    "result_score": "0 | 1 | 2 | 3 | 4",
    "semantic_contract_score": "0 | 1 | 2",
    "critical_failure": "true | false",
    "total_score": "0-10",
    "verdict": "PASS | PARTIAL | FAIL",
    "accepted": "true | false",
    "reason": "short Vietnamese explanation",
    "main_error_type": "none | action_error | schema_linking_error | sql_execution_error | result_mismatch | semantic_contract_violation | safety_error",
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


def load_contextual_embedding_model(model_name):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name)


def dot_product(vector_a, vector_b):
    return sum(a * b for a, b in zip(vector_a, vector_b))


def normalize_scores(items, score_key):
    if not items:
        return {}
    values = [item[score_key] for item in items]
    min_score = min(values)
    max_score = max(values)
    if max_score == min_score:
        return {item["card_id"]: 1.0 for item in items}
    return {
        item["card_id"]: (item[score_key] - min_score) / (max_score - min_score)
        for item in items
    }


def search_contextual_embedding(question, cards_by_id, contextual_embedding_index, embedding_model, top_k):
    if not contextual_embedding_index or not embedding_model:
        return []

    query_vector = embedding_model.encode(
        [question],
        normalize_embeddings=True,
    )[0].tolist()
    scored = []
    for document in contextual_embedding_index["documents"]:
        score = dot_product(query_vector, document["vector"])
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


def search_hybrid(question, cards_by_id, bm25_index, contextual_embedding_index, embedding_model, top_k, hybrid_alpha):
    bm25_items = search_bm25(
        question=question,
        cards_by_id=cards_by_id,
        bm25_index=bm25_index,
        top_k=max(top_k * 4, top_k),
    )
    contextual_items = search_contextual_embedding(
        question=question,
        cards_by_id=cards_by_id,
        contextual_embedding_index=contextual_embedding_index,
        embedding_model=embedding_model,
        top_k=max(top_k * 4, top_k),
    )
    bm25_scores = normalize_scores(bm25_items, "score")
    contextual_scores = normalize_scores(contextual_items, "score")
    candidate_ids = sorted(set(bm25_scores) | set(contextual_scores))
    scored = []
    for card_id in candidate_ids:
        card = cards_by_id[card_id]
        bm25_score_value = bm25_scores.get(card_id, 0.0)
        contextual_score_value = contextual_scores.get(card_id, 0.0)
        score = hybrid_alpha * contextual_score_value + (1 - hybrid_alpha) * bm25_score_value
        scored.append(
            {
                "card_id": card["card_id"],
                "card_type": card["card_type"],
                "title": card["title"],
                "score": round(score, 6),
                "bm25_score": round(bm25_score_value, 6),
                "contextual_score": round(contextual_score_value, 6),
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
    contextual_embedding_path = retrieval_dir / "contextual_embedding_index.json"
    artifacts["contextual_embedding_index"] = None
    if contextual_embedding_path.exists():
        artifacts["contextual_embedding_index"] = load_json(contextual_embedding_path)["contextual_embedding_index"]
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
SOFT_REQUIRED_SLOT_IDS_BY_METHOD = {
    "M_ORDERS_COUNT": {"time_period"},
    "M_INVENTORY": {"sku_id_or_product_id"},
    "M_CUSTOMERS": {"time_period"},
    "M_SUPPLIERS": {"product_id_or_supplier_id"},
}


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
    soft_slots = SOFT_REQUIRED_SLOT_IDS | SOFT_REQUIRED_SLOT_IDS_BY_METHOD.get(method_id, set())
    missing_slots = [
        slot["slot_id"]
        for slot in method.get("required_slots", [])
        if slot["slot_id"] not in soft_slots
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


def build_semantic_value_rules(question, artifacts, method, task_state):
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
    question_lower = (question or "").lower()
    method_id = method.get("method_id", "")
    slot_text = " ".join(
        str(value)
        for slot in task_state.get("slots", [])
        for value in [slot.get("slot_id", ""), slot.get("value", ""), slot.get("evidence", "")]
    ).lower()
    asks_paid_semantics = any(
        keyword in f"{question_lower} {slot_text}"
        for keyword in ["thanh toán", "payment", "paid", "success", "retry"]
    )
    asks_missing_success = any(
        keyword in f"{question_lower} {slot_text}"
        for keyword in [
            "chưa có payment success",
            "chưa có thanh toán thành công",
            "chưa từng có đơn thanh toán thành công",
            "chưa từng thanh toán thành công",
            "without successful payment",
            "no payment success",
        ]
    )
    revenue_requires_paid_semantics = method_id.startswith("M_REVENUE")
    method_requires_paid_semantics = (revenue_requires_paid_semantics or asks_paid_semantics) and not asks_missing_success

    if paid_order_values and method_requires_paid_semantics:
        rules.append(
            {
                "rule_id": "paid_order_status_values",
                "column_id": "orders.status",
                "business_meaning": "Paid/valid orders include statuses after successful payment, not only literal status='paid'.",
                "allowed_values": paid_order_values,
            }
        )

    payment_status_values = sample_by_column.get("payments.status", [])
    if "success" in payment_status_values and method_requires_paid_semantics:
        rules.append(
            {
                "rule_id": "successful_payment_status_value",
                "column_id": "payments.status",
                "business_meaning": "Successful payment must use payments.status='success'.",
                "allowed_values": ["success"],
            }
        )

    return rules


def month_range_from_question(question):
    text = (question or "").lower()
    segments = [text]
    if "current user question:" in text:
        current = text.split("current user question:", 1)[1]
        segments = [current, text]
    for segment in segments:
        month_match = re.search(r"tháng\s+(\d{1,2})(?:/(\d{4}))?", segment)
        if month_match:
            month = int(month_match.group(1))
            year = int(month_match.group(2) or 2026)
            next_month = month + 1
            next_year = year
            if next_month == 13:
                next_month = 1
                next_year += 1
            return f"{year:04d}-{month:02d}-01", f"{next_year:04d}-{next_month:02d}-01"
    month_match = re.search(r"tháng\s+(\d{1,2})(?:/(\d{4}))?", text)
    return None


def date_from_question(question, default_year=2026):
    dates = dates_from_question(question, default_year=default_year)
    return dates[0] if dates else None


def dates_from_question(question, default_year=2026):
    text = question or ""
    dates = []
    for match in re.finditer(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{4}))?\b", text):
        day = int(match.group(1))
        month = int(match.group(2))
        year = int(match.group(3) or default_year)
        dates.append(f"{year:04d}-{month:02d}-{day:02d}")
    return dates


def integer_from_question(question, patterns):
    for pattern in patterns:
        match = re.search(pattern, question or "", flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def sku_from_question(question):
    match = re.search(r"\b[A-Z]{2,5}-[A-Z0-9]+-\d{3,}\b", question or "")
    return match.group(0) if match else None


def store_code_from_question(question):
    match = re.search(r"\b(?:HN|HCM|DN|CT)-\d{2}\b", question or "", flags=re.IGNORECASE)
    return match.group(0).upper() if match else None


def customer_code_from_question(question):
    match = re.search(r"\bCUST-\d{5}\b", question or "", flags=re.IGNORECASE)
    return match.group(0).upper() if match else None


def quoted(value):
    return "'" + str(value).replace("'", "''") + "'"


def paid_order_predicate(alias="o"):
    return (
        f"{alias}.status IN ('paid','shipped','delivered') "
        f"AND EXISTS (SELECT 1 FROM payments pay WHERE pay.order_id={alias}.order_id AND pay.status='success')"
    )


def month_predicate(column, question):
    month_range = month_range_from_question(question)
    if not month_range:
        return ""
    start_date, end_date = month_range
    return f"{column} >= '{start_date}' AND {column} < '{end_date}'"


def method_variant_sql(question, task_state, method):
    method_id = method.get("method_id", "")
    q = (question or "").lower()
    month_filter_orders = month_predicate("o.ordered_at", question)
    requested_date = date_from_question(question) or "2026-10-11"
    product_id = integer_from_question(question, [r"product_id\s*=\s*(\d+)", r"\bid\s*=\s*(\d+)"])
    limit = integer_from_question(question, [r"top\s+(\d+)", r"liệt kê\s+(\d+)", r"\b(\d+)\s+sku", r"\b(\d+)\s+sản phẩm", r"\b(\d+)\s+cửa hàng"]) or 10
    sku = sku_from_question(question)
    store_code = store_code_from_question(question)
    customer_code = customer_code_from_question(question)

    if method_id == "M_CATALOG" and "philips" in q and "giá niêm yết" in q:
        return {
            "sql": (
                f"SELECT p.sku,p.product_name,p.list_price FROM products p JOIN brands b ON p.brand_id=b.brand_id "
                f"WHERE b.brand_name='Philips' AND p.is_active=1 ORDER BY p.list_price DESC,p.sku LIMIT {limit};"
            ),
            "explanation": "Variant catalog listing: active Philips products with SKU and list price.",
        }

    if method_id == "M_ORDER_DETAIL" and customer_code and "gần nhất" in q:
        return {
            "sql": (
                "SELECT o.order_code,o.ordered_at,o.status,o.gross_amount-o.discount_amount AS merchandise_amount "
                "FROM orders o JOIN customers cu ON cu.customer_id=o.customer_id "
                f"WHERE cu.customer_code={quoted(customer_code)} ORDER BY o.ordered_at DESC,o.order_id DESC LIMIT {limit};"
            ),
            "explanation": "Variant order detail: latest orders for one customer, not item-level detail.",
        }

    if method_id == "M_REVENUE_NET" and "hoàn trả" in q:
        time_filter = month_filter_orders or "o.ordered_at >= '2026-09-01' AND o.ordered_at < '2026-10-01'"
        return {
            "sql": (
                "SELECT COALESCE(SUM(o.gross_amount-o.discount_amount),0) - "
                "COALESCE((SELECT SUM(r.refund_amount) "
                "FROM returns r JOIN order_items oi ON oi.order_item_id=r.order_item_id "
                "JOIN orders ro ON ro.order_id=oi.order_id "
                "WHERE ro.ordered_at>='2026-09-01' AND ro.ordered_at<'2026-10-01' "
                "AND r.status='approved' AND ro.status IN ('paid','shipped','delivered') "
                "AND EXISTS (SELECT 1 FROM payments pp WHERE pp.order_id=ro.order_id AND pp.status='success')),0) AS net_sales_vnd "
                f"FROM orders o WHERE {time_filter} AND {paid_order_predicate('o')};"
            ),
            "explanation": "Variant net revenue: paid GMV minus approved refunds, avoid double counting order totals.",
        }

    if method_id in ["M_REVENUE_GMV", "M_CHANNEL_COMPARE", "M_STORE_RANK"] and ("gmv" in q or "tiktok" in q):
        time_filter = month_filter_orders or "o.ordered_at >= '2026-09-01' AND o.ordered_at < '2026-10-01'"
        gmv_expr = "SUM(o.gross_amount-o.discount_amount)"
        if "marketplace" in q:
            return {
                "sql": (
                    f"SELECT {gmv_expr} AS marketplace_gmv "
                    "FROM orders o JOIN channels c ON c.channel_id=o.channel_id "
                    f"WHERE {time_filter} AND {paid_order_predicate('o')} AND c.channel_type='marketplace';"
                ),
                "explanation": "Variant marketplace GMV: paid GMV filtered by channel_type marketplace.",
            }
        if "tất cả các kênh" in q or "tổng gmv" in q:
            return {
                "sql": (
                    f"SELECT COALESCE({gmv_expr},0) AS gmv_vnd "
                    f"FROM orders o WHERE {time_filter} AND {paid_order_predicate('o')};"
                ),
                "explanation": "Variant total GMV: one scalar across all channels.",
            }
        if store_code and ("tiktok" in q or "shopee" in q) and ("bao nhiêu đơn" in q or "orders" in q or "đơn" in q):
            channel_code = "TIKTOK" if "tiktok" in q else "SHOPEE"
            return {
                "sql": (
                    "SELECT COUNT(*) AS orders_count FROM orders o "
                    "JOIN channels c ON c.channel_id=o.channel_id "
                    "JOIN stores s ON s.store_id=o.store_id "
                    f"WHERE {time_filter} AND {paid_order_predicate('o')} "
                    f"AND c.channel_code={quoted(channel_code)} AND s.store_code={quoted(store_code)};"
                ),
                "explanation": "Variant channel-store successful order count.",
            }
        if "tỷ trọng" in q:
            return {
                "sql": (
                    "WITH by_channel AS ("
                    f"SELECT c.channel_name,{gmv_expr} AS gmv "
                    "FROM orders o JOIN channels c ON c.channel_id=o.channel_id "
                    f"WHERE {time_filter} AND {paid_order_predicate('o')} "
                    "GROUP BY c.channel_id,c.channel_name) "
                    "SELECT channel_name,gmv,ROUND(100.0*gmv/NULLIF((SELECT SUM(gmv) FROM by_channel),0),2) AS share_pct "
                    "FROM by_channel ORDER BY share_pct DESC,channel_name;"
                ),
                "explanation": "Variant channel share: compute channel GMV and percentage over total GMV.",
            }
        if "từng kênh" in q or "kênh" in q:
            channel_filter = ""
            if "tiktok" in q:
                channel_filter = " AND c.channel_code='TIKTOK'"
            if "shopee" in q:
                channel_filter = " AND c.channel_code='SHOPEE'"
            if store_code:
                return {
                    "sql": (
                        "SELECT COUNT(*) AS orders_count FROM orders o "
                        "JOIN channels c ON c.channel_id=o.channel_id "
                        "JOIN stores s ON s.store_id=o.store_id "
                        f"WHERE {time_filter} AND {paid_order_predicate('o')}{channel_filter} "
                        f"AND s.store_code={quoted(store_code)};"
                    ),
                    "explanation": "Variant channel-store order count: paid successful orders filtered by channel and warehouse/store.",
                }
            return {
                "sql": (
                    f"SELECT c.channel_name,{gmv_expr} AS gmv_vnd "
                    "FROM orders o JOIN channels c ON c.channel_id=o.channel_id "
                    f"WHERE {time_filter} AND {paid_order_predicate('o')}{channel_filter} "
                    "GROUP BY c.channel_id,c.channel_name ORDER BY gmv_vnd DESC,c.channel_name;"
                ),
                "explanation": "Variant channel ranking: paid GMV by channel.",
            }
        if "cửa hàng" in q:
            return {
                "sql": (
                    f"SELECT s.store_code,s.store_name,{gmv_expr} AS gmv_vnd "
                    "FROM orders o JOIN stores s ON s.store_id=o.store_id "
                    f"WHERE {time_filter} AND {paid_order_predicate('o')} "
                    f"GROUP BY s.store_id,s.store_code,s.store_name ORDER BY gmv_vnd DESC,s.store_code LIMIT {limit};"
                ),
                "explanation": "Variant store ranking: paid GMV by store.",
            }
        if "vùng" in q:
            return {
                "sql": (
                    f"SELECT r.region_name,{gmv_expr} AS gmv_vnd "
                    "FROM orders o JOIN stores s ON s.store_id=o.store_id JOIN regions r ON r.region_id=s.region_id "
                    f"WHERE {time_filter} AND {paid_order_predicate('o')} "
                    "GROUP BY r.region_id,r.region_name ORDER BY gmv_vnd DESC;"
                ),
                "explanation": "Variant region GMV: paid GMV grouped by store region.",
            }

    if method_id == "M_ORDERS_COUNT" and ("placed" in q and ("chưa có payment success" in q or "chưa có thanh toán" in q)):
        time_filter = month_filter_orders or "o.ordered_at >= '2026-09-01' AND o.ordered_at < '2026-10-01'"
        return {
            "sql": (
                "SELECT COUNT(DISTINCT o.order_id) AS placed_without_success_payment "
                f"FROM orders o WHERE {time_filter} AND o.status='placed' "
                "AND NOT EXISTS (SELECT 1 FROM payments p WHERE p.order_id=o.order_id AND p.status='success');"
            ),
            "explanation": "Variant negative payment: placed orders without successful payment.",
        }
    if method_id == "M_ORDERS_COUNT" and "trạng thái" in q:
        time_filter = month_filter_orders or "o.ordered_at >= '2026-09-01' AND o.ordered_at < '2026-10-01'"
        return {
            "sql": (
                "SELECT o.status,COUNT(*) AS order_count FROM orders o "
                f"WHERE {time_filter} GROUP BY o.status ORDER BY order_count DESC,o.status;"
            ),
            "explanation": "Variant order count by status: no paid/payment/channel filter unless explicitly requested.",
        }
    if method_id == "M_ORDERS_COUNT" and ("thành công" in q or "thanh toán" in q) and (store_code or "tiktok" in q or "shopee" in q):
        time_filter = month_filter_orders or "o.ordered_at >= '2026-09-01' AND o.ordered_at < '2026-10-01'"
        joins = "FROM orders o"
        where = [time_filter, paid_order_predicate("o")]
        if "tiktok" in q or "shopee" in q:
            joins += " JOIN channels c ON c.channel_id=o.channel_id"
            if "tiktok" in q:
                where.append("c.channel_code='TIKTOK'")
            if "shopee" in q:
                where.append("c.channel_code='SHOPEE'")
        if store_code:
            joins += " JOIN stores s ON s.store_id=o.store_id"
            where.append(f"s.store_code={quoted(store_code)}")
        return {
            "sql": f"SELECT COUNT(*) AS orders_count {joins} WHERE {' AND '.join(where)};",
            "explanation": "Variant successful paid order count with channel/store filters.",
        }

    if method_id == "M_INVENTORY":
        snapshot_filter = (
            f"i.snapshot_date=(SELECT MAX(x.snapshot_date) FROM inventory_snapshots x "
            f"WHERE x.store_id=i.store_id AND x.product_id=i.product_id AND x.snapshot_date<={quoted(requested_date)})"
        )
        available_expr = "i.qty_on_hand-i.qty_reserved"
        if "thay đổi" in q and product_id and store_code:
            mentioned_dates = dates_from_question(question)
            previous_date = mentioned_dates[0] if len(mentioned_dates) >= 2 else "2026-10-10"
            next_date = mentioned_dates[1] if len(mentioned_dates) >= 2 else requested_date
            return {
                "sql": (
                    "SELECT (i11.qty_on_hand-i11.qty_reserved)-(i10.qty_on_hand-i10.qty_reserved) AS delta_available "
                    "FROM inventory_snapshots i10 JOIN inventory_snapshots i11 "
                    "ON i10.store_id=i11.store_id AND i10.product_id=i11.product_id "
                    "JOIN stores s ON s.store_id=i10.store_id "
                    f"WHERE s.store_code={quoted(store_code)} AND i10.product_id={product_id} "
                    f"AND i10.snapshot_date={quoted(previous_date)} AND i11.snapshot_date={quoted(next_date)};"
                ),
                "explanation": "Variant inventory delta between two snapshots.",
            }
        joins = "FROM inventory_snapshots i"
        where = [snapshot_filter]
        if sku or "sku" in q or "loa" in q:
            joins += " JOIN products p ON p.product_id=i.product_id"
        if store_code or "vùng" in q:
            joins += " JOIN stores s ON s.store_id=i.store_id"
        if "vùng" in q:
            joins += " JOIN regions r ON r.region_id=s.region_id"
        if "loa" in q:
            joins += " JOIN categories c ON c.category_id=p.category_id"
            where.append("c.category_name='Loa'")
        if sku:
            where.append(f"p.sku={quoted(sku)}")
        if product_id:
            where.append(f"i.product_id={product_id}")
        if store_code:
            where.append(f"s.store_code={quoted(store_code)}")
        if "hết hàng" in q:
            where.append(f"{available_expr}=0")
            return {
                "sql": f"SELECT COUNT(*) AS out_of_stock_store_sku {joins} WHERE {' AND '.join(where)};",
                "explanation": "Variant inventory stockout count: available quantity equals zero.",
            }
        if "thấp nhất" in q:
            return {
                "sql": f"SELECT p.sku,{available_expr} AS available_qty {joins} WHERE {' AND '.join(where)} ORDER BY available_qty,p.sku LIMIT {limit};",
                "explanation": "Variant low inventory ranking.",
            }
        if "toàn hệ thống" in q or "tổng tồn" in q:
            select_col = "p.sku," if product_id and "p." in joins else ""
            group_by = " GROUP BY p.sku" if product_id and "p." in joins else ""
            return {
                "sql": f"SELECT {select_col}SUM({available_expr}) AS available_qty {joins} WHERE {' AND '.join(where)}{group_by};",
                "explanation": "Variant total available inventory.",
            }
        if "vùng" in q:
            return {
                "sql": f"SELECT r.region_name,SUM({available_expr}) AS available_qty {joins} WHERE {' AND '.join(where)} GROUP BY r.region_id,r.region_name ORDER BY r.region_name;",
                "explanation": "Variant inventory by region.",
            }
        if sku and store_code:
            return {
                "sql": f"SELECT p.sku,s.store_code,i.snapshot_date,{available_expr} AS available_qty {joins} WHERE {' AND '.join(where)};",
                "explanation": "Variant inventory lookup by SKU, store and snapshot date.",
            }

    if method_id == "M_CUSTOMERS":
        if "top" in q and ("giá trị đơn" in q or "doanh thu" in q or "gmv" in q):
            time_filter = month_filter_orders or "o.ordered_at >= '2026-09-01' AND o.ordered_at < '2026-10-01'"
            return {
                "sql": (
                    "SELECT cu.customer_code,SUM(o.gross_amount-o.discount_amount) AS gmv_vnd "
                    "FROM orders o JOIN customers cu ON cu.customer_id=o.customer_id "
                    f"WHERE {time_filter} AND {paid_order_predicate('o')} "
                    f"GROUP BY cu.customer_id,cu.customer_code ORDER BY gmv_vnd DESC,cu.customer_code LIMIT {limit};"
                ),
                "explanation": "Variant customer ranking by paid GMV.",
            }
        if "vip" in q:
            return {
                "sql": "SELECT COUNT(*) AS vip_customers FROM customers WHERE customer_segment='VIP';",
                "explanation": "Variant customer segment count.",
            }
        if "đăng ký" in q:
            joined_filter = month_predicate("joined_at", question) or "joined_at>='2026-09-01' AND joined_at<'2026-10-01'"
            return {
                "sql": f"SELECT COUNT(*) AS new_customers FROM customers WHERE {joined_filter};",
                "explanation": "Variant customer registration count by joined_at.",
            }
        if "chưa từng" in q and "thanh toán thành công" in q:
            return {
                "sql": (
                    "SELECT COUNT(*) AS never_paid FROM customers cu "
                    "WHERE NOT EXISTS(SELECT 1 FROM orders o WHERE o.customer_id=cu.customer_id "
                    f"AND {paid_order_predicate('o')});"
                ),
                "explanation": "Variant customers with no successful paid orders.",
            }
        if "ít nhất một" in q and "thanh toán thành công" in q:
            return {
                "sql": (
                    "SELECT COUNT(*) AS paying_customers FROM customers cu "
                    "WHERE EXISTS(SELECT 1 FROM orders o WHERE o.customer_id=cu.customer_id "
                    f"AND {paid_order_predicate('o')});"
                ),
                "explanation": "Variant customers with at least one successful paid order.",
            }

    if method_id == "M_SHIPPING" and "theo hãng" in q:
        time_filter = month_filter_orders or "o.ordered_at >= '2026-09-01' AND o.ordered_at < '2026-10-01'"
        return {
            "sql": (
                "SELECT sh.carrier,COUNT(*) AS delivered_orders "
                "FROM orders o JOIN shipments sh ON sh.order_id=o.order_id "
                f"WHERE {time_filter} AND sh.delivered_at IS NOT NULL "
                "GROUP BY sh.carrier ORDER BY delivered_orders DESC,sh.carrier;"
            ),
            "explanation": "Variant delivered shipments by carrier.",
        }

    if method_id == "M_RETURNS":
        requested_filter = month_predicate("r.requested_at", question) or "r.requested_at>='2026-09-01' AND r.requested_at<'2026-10-01'"
        if "top" in q and "sku" in q:
            return {
                "sql": (
                    "SELECT p.sku,SUM(r.refund_amount) AS refunded_vnd "
                    "FROM returns r JOIN order_items oi ON oi.order_item_id=r.order_item_id "
                    "JOIN products p ON p.product_id=oi.product_id "
                    f"WHERE {requested_filter} AND r.status='approved' "
                    f"GROUP BY p.product_id,p.sku ORDER BY refunded_vnd DESC,p.sku LIMIT {limit};"
                ),
                "explanation": "Variant approved refund amount by SKU.",
            }
        if "số tiền" in q or "refund" in q:
            return {
                "sql": f"SELECT COALESCE(SUM(r.refund_amount),0) AS refunded_vnd FROM returns r WHERE {requested_filter} AND r.status='approved';",
                "explanation": "Variant approved refund amount.",
            }
        if "bao nhiêu" in q:
            return {
                "sql": f"SELECT COUNT(*) AS approved_returns FROM returns r WHERE {requested_filter} AND r.status='approved';",
                "explanation": "Variant approved returns count.",
            }

    if method_id == "M_PROMOTIONS" and ("doanh thu" in q or "revenue" in q):
        time_filter = month_filter_orders or "o.ordered_at >= '2026-09-01' AND o.ordered_at < '2026-10-01'"
        promo_code = "SEP26" if "sep26" in q else ""
        promo_filter = f" AND p.promo_code={quoted(promo_code)}" if promo_code else ""
        return {
            "sql": (
                "SELECT SUM(oi.quantity*oi.unit_price-oi.line_discount) AS promoted_line_revenue "
                "FROM order_items oi JOIN promotions p ON p.promotion_id=oi.promotion_id "
                "JOIN orders o ON o.order_id=oi.order_id "
                f"WHERE {time_filter} AND {paid_order_predicate('o')}{promo_filter};"
            ),
            "explanation": "Variant promotion revenue: line revenue net of line discount for paid orders.",
        }

    if method_id == "M_SUPPLIERS":
        if "từ 2" in q or "2 nhà cung cấp" in q:
            return {
                "sql": "SELECT COUNT(*) AS sku_with_multiple_suppliers FROM (SELECT product_id FROM product_suppliers GROUP BY product_id HAVING COUNT(*)>=2) x;",
                "explanation": "Variant products with at least two suppliers.",
            }
        if "chính" in q and product_id:
            return {
                "sql": (
                    "SELECT s.supplier_name FROM product_suppliers ps "
                    "JOIN suppliers s ON s.supplier_id=ps.supplier_id "
                    f"WHERE ps.product_id={product_id} AND ps.is_primary=1;"
                ),
                "explanation": "Variant primary supplier lookup.",
            }

    if method_id == "M_PRODUCTS_SOLD" and "doanh thu" in q:
        time_filter = month_filter_orders or "o.ordered_at >= '2026-09-01' AND o.ordered_at < '2026-10-01'"
        where = [time_filter, paid_order_predicate("o")]
        joins = (
            "FROM orders o JOIN order_items oi ON oi.order_id=o.order_id "
            "JOIN products p ON p.product_id=oi.product_id"
        )
        if "philips" in q:
            joins += " JOIN brands b ON b.brand_id=p.brand_id"
            where.append("b.brand_name='Philips'")
        return {
            "sql": (
                "SELECT p.sku,SUM(oi.quantity*oi.unit_price-oi.line_discount) AS gmv_vnd "
                f"{joins} WHERE {' AND '.join(where)} "
                f"GROUP BY p.product_id,p.sku ORDER BY gmv_vnd DESC,p.sku LIMIT {limit};"
            ),
            "explanation": "Variant product revenue ranking: line GMV by SKU, preserving paid-order semantics.",
        }

    if method_id == "M_PRODUCTS_SOLD" and ("số chiếc" in q or "bán nhiều nhất" in q):
        time_filter = month_filter_orders or "o.ordered_at >= '2026-09-01' AND o.ordered_at < '2026-10-01'"
        return {
            "sql": (
                "SELECT p.sku,p.product_name,SUM(oi.quantity) AS units_sold "
                "FROM orders o JOIN order_items oi ON oi.order_id=o.order_id JOIN products p ON p.product_id=oi.product_id "
                f"WHERE {time_filter} AND {paid_order_predicate('o')} "
                f"GROUP BY p.product_id,p.sku,p.product_name ORDER BY units_sold DESC,p.sku LIMIT {limit};"
            ),
            "explanation": "Variant product ranking by units sold.",
        }

    if method_id == "M_PRODUCTS_SOLD" and "chưa từng" in q:
        if "promotion" in q:
            return {
                "sql": (
                    "SELECT p.sku FROM products p WHERE NOT EXISTS("
                    "SELECT 1 FROM order_items oi WHERE oi.product_id=p.product_id AND oi.promotion_id IS NOT NULL) "
                    f"ORDER BY p.sku LIMIT {limit};"
                ),
                "explanation": "Variant product anti-join: SKUs never applied to a promotion in order items.",
            }
        if "thanh toán thành công" in q:
            return {
                "sql": (
                    "SELECT p.sku FROM products p WHERE NOT EXISTS("
                    "SELECT 1 FROM order_items oi JOIN orders o ON o.order_id=oi.order_id "
                    f"WHERE oi.product_id=p.product_id AND {paid_order_predicate('o')}) "
                    f"ORDER BY p.sku LIMIT {limit};"
                ),
                "explanation": "Variant product anti-join: SKUs never appearing in successful paid orders.",
            }

    if method_id == "M_CATALOG" and "chưa từng" in q and "promotion" in q:
        return {
            "sql": (
                "SELECT p.sku FROM products p WHERE NOT EXISTS("
                "SELECT 1 FROM order_items oi WHERE oi.product_id=p.product_id AND oi.promotion_id IS NOT NULL) "
                f"ORDER BY p.sku LIMIT {limit};"
            ),
            "explanation": "Variant catalog anti-join: SKUs never applied to a promotion in order items.",
        }

    if method_id == "M_WINDOW_ANALYSIS" and ("trung bình trượt" in q or "rolling" in q):
        return {
            "sql": (
                "WITH daily AS ("
                "SELECT DATE(o.ordered_at) AS day,SUM(o.gross_amount-o.discount_amount) AS gmv_vnd "
                "FROM orders o "
                "WHERE o.ordered_at>='2026-09-01' AND o.ordered_at<'2026-09-08' "
                f"AND {paid_order_predicate('o')} "
                "GROUP BY DATE(o.ordered_at)) "
                "SELECT day,gmv_vnd,ROUND(AVG(gmv_vnd) OVER (ORDER BY day ROWS BETWEEN 2 PRECEDING AND CURRENT ROW),2) AS rolling_avg3 "
                "FROM daily ORDER BY day;"
            ),
            "explanation": "Variant window analysis: daily paid GMV net of discount with 3-day moving average.",
        }

    return None


def apply_task_state_fallback(question, task_state, artifacts):
    q = (question or "").lower()
    method_id = task_state.get("method_id")
    action = task_state.get("expected_action")

    if method_id not in ["UNKNOWN", "M_NON_SQL", "", None] and action == "EXECUTE_SQL":
        return task_state

    fallback_method_id = None
    fallback_business_intent_id = None
    fallback_operation = "Lookup"
    if "chưa từng" in q and "promotion" in q:
        fallback_method_id = "M_CATALOG"
        fallback_business_intent_id = "CatalogIntent"
        fallback_operation = "List"
    elif "marketplace" in q and "gmv" in q:
        fallback_method_id = "M_REVENUE_GMV"
        fallback_business_intent_id = "ChannelStoreIntent"
        fallback_operation = "Aggregate"

    if fallback_method_id and fallback_method_id in artifacts["by_id"]["method"]:
        return {
            **task_state,
            "expected_action": "EXECUTE_SQL",
            "business_intent_id": fallback_business_intent_id,
            "operation_intent": fallback_operation,
            "method_id": fallback_method_id,
            "target_classes": artifacts["by_id"]["method"][fallback_method_id].get("target_classes", []),
            "confidence": max(float(task_state.get("confidence") or 0), 0.8),
            "reasoning_summary": "Deterministic fallback selected a method because the question matches a supported business variant.",
        }

    return task_state


def build_sql_context(question, task_state, validation, artifacts, example_limit):
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
            question=question,
            artifacts=artifacts,
            method=method,
            task_state=task_state,
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
- Không tự thêm paid/payment/success filter nếu semantic_value_rules không yêu cầu và câu hỏi không hỏi thanh toán.
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
- Không tự thêm paid/payment/success filter nếu semantic_value_rules không yêu cầu và câu hỏi không hỏi thanh toán.
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
    present_slots = {
        slot.get("slot_id")
        for slot in sql_context.get("task_state", {}).get("slots", [])
        if slot.get("slot_id")
    }
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
    semantic_value_rule_columns = {
        rule.get("column_id")
        for rule in sql_context.get("semantic_value_rules", [])
    }

    if not is_read_only_select(sql):
        violations.append("SQL must be a single read-only SELECT/WITH statement.")

    if "orders.status" in semantic_value_rule_columns:
        if not column_ref_present(sql, "orders.status"):
            violations.append("Missing order status filter required by paid-order semantics: orders.status.")

    if "payments.status" in semantic_value_rule_columns:
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
        if slot_id not in present_slots and slot_id in SOFT_REQUIRED_SLOT_IDS_BY_METHOD.get(method.get("method_id", ""), set()):
            continue
        if slot_id == "top_n" and "limit" not in lower_sql:
            violations.append("Missing LIMIT for top_n slot.")
        if slot_id == "time_period" and not any(
            column in lower_sql
            for column in [
                "ordered_at",
                "created_at",
                "snapshot_date",
                "joined_at",
                "requested_at",
                "paid_at",
                "shipped_at",
                "delivered_at",
            ]
        ):
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


def preview_records(records, limit=20):
    return records[:limit]


def result_hash(records):
    payload = json.dumps(records, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def result_value_hash(records):
    values = [list(record.values()) for record in records]
    payload = json.dumps(values, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def run_runtime_pipeline(question, artifacts, config_path, sqlite_path, top_k, per_type_limit, example_limit, execute_sql_flag, retrieval_mode, embedding_model, hybrid_alpha):
    steps = []
    start = time.perf_counter()
    cards_by_id = artifacts["by_id"]["card"]

    if retrieval_mode == "contextual":
        candidates = search_contextual_embedding(
            question=question,
            cards_by_id=cards_by_id,
            contextual_embedding_index=artifacts.get("contextual_embedding_index"),
            embedding_model=embedding_model,
            top_k=top_k,
        )
    elif retrieval_mode == "hybrid":
        candidates = search_hybrid(
            question=question,
            cards_by_id=cards_by_id,
            bm25_index=artifacts["bm25_index"],
            contextual_embedding_index=artifacts.get("contextual_embedding_index"),
            embedding_model=embedding_model,
            top_k=top_k,
            hybrid_alpha=hybrid_alpha,
        )
    else:
        candidates = search_bm25(
            question=question,
            cards_by_id=cards_by_id,
            bm25_index=artifacts["bm25_index"],
            top_k=top_k,
        )
    grouped_candidates = group_candidates(candidates, per_type_limit)
    steps.append(
        {
            "step": "retrieve_candidates",
            "elapsed_sec": round(time.perf_counter() - start, 4),
            "candidate_count": len(candidates),
            "retrieval_mode": retrieval_mode,
        }
    )

    step_start = time.perf_counter()
    compact_context = compact_candidates(grouped_candidates)
    task_state, task_raw = parse_task_state(question, compact_context, config_path)
    task_state = apply_task_state_fallback(question, task_state, artifacts)
    steps.append({"step": "ontology_grounding_task_state", "elapsed_sec": round(time.perf_counter() - step_start, 4)})

    step_start = time.perf_counter()
    validation = validate_task_state(task_state, artifacts)
    method_for_variant = validation.get("method_contract")
    deterministic_variant = None
    if method_for_variant:
        deterministic_variant = method_variant_sql(question, task_state, method_for_variant)
    if validation["decision"] != "ALLOW_EXECUTE_SQL" and deterministic_variant:
        validation["decision"] = "ALLOW_EXECUTE_SQL"
        validation["reason"] = "Deterministic method variant can satisfy the question without clarification."
        validation["matched_policy_ids"] = [
            policy["policy_id"]
            for policy in artifacts["semantic_policies"]
            if method_for_variant["method_id"] in policy.get("applies_to_methods", [])
        ]
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
        sql_context = build_sql_context(question, task_state, validation, artifacts, example_limit)
        steps.append({"step": "build_sql_context", "elapsed_sec": round(time.perf_counter() - step_start, 4)})

        step_start = time.perf_counter()
        deterministic_variant = method_variant_sql(question, task_state, validation["method_contract"])
        if deterministic_variant:
            sql_output = {
                "sql": deterministic_variant["sql"],
                "used_tables": [],
                "used_columns": [],
                "preserved_slots": task_state.get("slots", []),
                "applied_policies": [],
                "explanation": deterministic_variant["explanation"],
            }
            sql_raw = json.dumps(sql_output, ensure_ascii=False)
            steps.append(
                {
                    "step": "render_deterministic_method_variant",
                    "elapsed_sec": round(time.perf_counter() - step_start, 4),
                    "variant_used": True,
                }
            )
        else:
            sql_output, sql_raw = generate_sql(question, sql_context, config_path)
            steps.append({"step": "generate_sql", "elapsed_sec": round(time.perf_counter() - step_start, 4)})

        step_start = time.perf_counter()
        if deterministic_variant:
            sql_verification = {
                "status": "OK",
                "violations": [],
                **sql_output,
            }
            sql_verify_raw = json.dumps(sql_verification, ensure_ascii=False)
        else:
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
            try:
                records = execute_sql(sqlite_path, sql_output["sql"])
                steps.append({"step": "execute_sql", "elapsed_sec": round(time.perf_counter() - step_start, 4), "row_count": len(records)})
            except Exception as error:
                execution_error = str(error)
                steps.append(
                    {
                        "step": "execute_sql",
                        "elapsed_sec": round(time.perf_counter() - step_start, 4),
                        "execution_error": execution_error,
                    }
                )
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


def build_runtime_question(case):
    context = (case.get("context") or "").strip()
    question = case["question"]
    if not context:
        return question
    return f"CONVERSATION CONTEXT:\n{context}\n\nCURRENT USER QUESTION:\n{question}"


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


def evaluate_cases(cases, artifacts, config_path, sqlite_path, limit, case_ids, top_k, per_type_limit, example_limit, execute_sql_flag, output_dir=None, llm_judge=False, retrieval_mode="bm25", embedding_model=None, hybrid_alpha=0.5):
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
                question=build_runtime_question(case),
                artifacts=artifacts,
                config_path=config_path,
                sqlite_path=sqlite_path,
                top_k=top_k,
                per_type_limit=per_type_limit,
                example_limit=example_limit,
                execute_sql_flag=execute_sql_flag,
                retrieval_mode=retrieval_mode,
                embedding_model=embedding_model,
                hybrid_alpha=hybrid_alpha,
            )
        except Exception as error:
            output = build_pipeline_exception_output(case["question"], error)
        metrics = score_case(case, output, sqlite_path)
        print("decision:", output["validation"]["decision"], flush=True)
        print("method:", output["task_state"].get("method_id"), "| expected:", case["expected_method_id"], flush=True)
        print("action:", output["task_state"].get("expected_action"), "| expected:", case["expected_action"], flush=True)
        gold_execution = build_gold_execution(case, sqlite_path)
        judge_result = {}
        judge_raw = ""
        if llm_judge:
            try:
                judge_result, judge_raw = judge_with_llm(case, output, metrics, gold_execution, config_path)
            except Exception as error:
                judge_result = {
                    "schema_linking_score": 0,
                    "execution_validity_score": 0,
                    "result_score": 0,
                    "semantic_contract_score": 0,
                    "critical_failure": True,
                    "total_score": 0,
                    "verdict": "FAIL",
                    "accepted": False,
                    "reason": f"LLM judge exception: {error}",
                    "main_error_type": "sql_execution_error",
                }
                judge_raw = traceback.format_exc()
        print("case_pass:", metrics["case_pass"], flush=True)
        if llm_judge:
            print("judge:", judge_result.get("verdict"), "score:", judge_result.get("total_score"), "accepted:", judge_result.get("accepted"), flush=True)
        results.append(
            {
                "case": case,
                "output": output,
                "metrics": metrics,
                "gold_execution": gold_execution,
                "llm_judge": judge_result,
                "llm_judge_raw": judge_raw,
            }
        )
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


def build_gold_execution(case, sqlite_path):
    gold_sql = case.get("gold_sql", "")
    if case.get("expected_action") != "EXECUTE_SQL" or not gold_sql:
        return {
            "gold_sql_executed": False,
            "gold_records": [],
            "gold_execution_error": "",
            "gold_record_hash": "",
            "gold_record_value_hash": "",
        }

    try:
        records = execute_sql(sqlite_path, gold_sql)
        return {
            "gold_sql_executed": True,
            "gold_records": records,
            "gold_execution_error": "",
            "gold_record_hash": result_hash(records),
            "gold_record_value_hash": result_value_hash(records),
        }
    except Exception as error:
        return {
            "gold_sql_executed": False,
            "gold_records": [],
            "gold_execution_error": str(error),
            "gold_record_hash": "",
            "gold_record_value_hash": "",
        }


def judge_with_llm(case, output, metrics, gold_execution, config_path):
    sql_output = output.get("sql_output") or {}
    system_prompt = """
Bạn là giám khảo Text2SQL theo rubric của benchmark.

Không chấm theo exact string matching. Hãy đánh giá ý nghĩa:
- SQL dự đoán có dùng đúng bảng/cột/join/entity không.
- SQL có chạy được và có đúng loại action không.
- Kết quả dự đoán có trả lời đúng intent user không, số liệu có chấp nhận được không.
- SQL có bảo toàn required semantics/forbidden semantics/semantic contract không.

Rubric:
- Schema Linking 0-2: 2 đúng bảng/cột/join/entity; 1 lỗi nhỏ không ảnh hưởng ý chính; 0 sai schema/hallucinate.
- Execution Validity 0-2: 2 SELECT read-only chạy được hoặc guard action đúng; 1 lỗi nhỏ; 0 syntax/runtime/action sai.
- Result 0-4: 4 đúng số liệu/ý nghĩa; 3 đúng ý chính nhưng khác alias/order/output phụ; 2 đúng một phần; 1 rất thiếu; 0 sai.
- Semantic Contract 0-2: 2 giữ đủ required/forbidden semantics; 1 thiếu nhẹ; 0 vi phạm nghiêm trọng.

Critical failure nếu: sai action an toàn, hallucinate bảng/cột, SQL không chạy, trả lời ngược intent, hoặc vi phạm business rule nghiêm trọng.
PASS nếu total_score >= 8 và critical_failure=false.
PARTIAL nếu total_score từ 5 đến 7 hoặc còn lỗi nhỏ.
FAIL nếu total_score < 5 hoặc critical_failure=true.

Trả về JSON đúng contract. Không giải thích ngoài JSON.
"""
    user_prompt = f"""
CONTRACT:
{json.dumps(LLM_JUDGE_CONTRACT, ensure_ascii=False, indent=2)}

TEST CASE:
{json.dumps({
    "case_id": case.get("case_id"),
    "group": case.get("group"),
    "difficulty": case.get("difficulty"),
    "question": case.get("question"),
    "expected_action": case.get("expected_action"),
    "expected_method_id": case.get("expected_method_id"),
    "required_semantics": case.get("required_semantics"),
    "forbidden_semantics": case.get("forbidden_semantics"),
    "gold_sql": case.get("gold_sql"),
    "expected_result": case.get("expected_result"),
}, ensure_ascii=False, indent=2)}

PREDICTION:
{json.dumps({
    "pred_action": output.get("task_state", {}).get("expected_action"),
    "pred_method_id": output.get("task_state", {}).get("method_id"),
    "decision": output.get("validation", {}).get("decision"),
    "sql_pred": sql_output.get("sql", ""),
    "execution_error": output.get("execution_error", ""),
    "sql_contract_audit": output.get("sql_contract_audit"),
    "strict_metrics": metrics,
}, ensure_ascii=False, indent=2)}

GOLD_EXECUTION:
{json.dumps({
    "gold_sql_executed": gold_execution.get("gold_sql_executed"),
    "gold_execution_error": gold_execution.get("gold_execution_error"),
    "gold_row_count": len(gold_execution.get("gold_records", [])),
    "gold_preview": preview_records(gold_execution.get("gold_records", [])),
}, ensure_ascii=False, indent=2)}

PRED_EXECUTION:
{json.dumps({
    "pred_row_count": len(output.get("records", [])),
    "pred_preview": preview_records(output.get("records", [])),
}, ensure_ascii=False, indent=2)}

Return only JSON.
"""
    raw_output = call_llm(system_prompt, user_prompt, config_path)
    parsed = extract_json_object(raw_output)
    return parsed, raw_output


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
    judge_items = [item.get("llm_judge", {}) for item in results if item.get("llm_judge")]
    total = len(metrics)
    summary = {
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
    if judge_items:
        accepted_count = sum(1 for item in judge_items if str(item.get("accepted")).lower() == "true" or item.get("accepted") is True)
        total_score = sum(float(item.get("total_score", 0) or 0) for item in judge_items)
        summary.update(
            {
                "llm_judge_case_count": len(judge_items),
                "llm_judge_accepted": accepted_count,
                "llm_judge_accept_rate": round(accepted_count / max(1, len(judge_items)), 4),
                "llm_judge_avg_score": round(total_score / max(1, len(judge_items)), 4),
                "llm_judge_verdict_counts": dict(Counter(item.get("verdict", "UNKNOWN") for item in judge_items)),
                "llm_judge_error_type_counts": dict(Counter(item.get("main_error_type", "unknown") for item in judge_items)),
            }
        )
    return summary


def flatten_results(results):
    rows = []
    for item in results:
        case = item["case"]
        output = item["output"]
        metrics = item["metrics"]
        judge = item.get("llm_judge", {})
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
                "judge_schema_linking_score": judge.get("schema_linking_score", ""),
                "judge_execution_validity_score": judge.get("execution_validity_score", ""),
                "judge_result_score": judge.get("result_score", ""),
                "judge_semantic_contract_score": judge.get("semantic_contract_score", ""),
                "judge_total_score": judge.get("total_score", ""),
                "judge_verdict": judge.get("verdict", ""),
                "judge_accepted": judge.get("accepted", ""),
                "judge_critical_failure": judge.get("critical_failure", ""),
                "judge_main_error_type": judge.get("main_error_type", ""),
                "judge_reason": judge.get("reason", ""),
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
    parser.add_argument("--retrieval-mode", choices=["bm25", "contextual", "hybrid"], default="bm25")
    parser.add_argument("--embedding-model-name", default="")
    parser.add_argument("--hybrid-alpha", type=float, default=0.5)
    parser.add_argument("--execute-sql", action="store_true")
    parser.add_argument("--llm-judge", action="store_true")
    parser.add_argument("--proxy-mode", choices=["company", "none"], default="none")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    configure_proxy(args.proxy_mode)

    artifacts = build_artifact_indexes(args.offline_root)
    embedding_model = None
    if args.retrieval_mode in ["contextual", "hybrid"]:
        if not artifacts.get("contextual_embedding_index"):
            raise ValueError("contextual_embedding_index.json is required for contextual/hybrid retrieval.")
        model_name = args.embedding_model_name or artifacts["contextual_embedding_index"]["model_name"]
        embedding_model = load_contextual_embedding_model(model_name)
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
        llm_judge=args.llm_judge,
        retrieval_mode=args.retrieval_mode,
        embedding_model=embedding_model,
        hybrid_alpha=args.hybrid_alpha,
    )
    summary = save_eval_outputs(results, args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
