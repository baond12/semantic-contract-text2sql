import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_json(data, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def as_text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def join_text(*parts):
    return "\n".join(part for part in [as_text(item).strip() for item in parts] if part)


def tokenize(text):
    text = (text or "").lower()
    tokens = re.findall(r"[\w]+", text, flags=re.UNICODE)
    return [token for token in tokens if len(token) > 1]


def make_card(card_id, card_type, title, text, metadata, source_file):
    return {
        "card_id": card_id,
        "card_type": card_type,
        "title": title,
        "text": text,
        "tokens": tokenize(text),
        "metadata": metadata,
        "source_file": source_file,
    }


def build_business_intent_cards(task_ontology_dir):
    path = Path(task_ontology_dir) / "business_intents.json"
    items = load_json(path)["business_intents"]
    cards = []
    for item in items:
        text = join_text(
            item.get("business_intent_name"),
            item.get("description"),
            "source_group: " + as_text(item.get("source_group")),
            "related_classes: " + as_text(item.get("related_classes", [])),
            "allowed_methods: " + as_text(item.get("allowed_methods", [])),
            "allowed_operation_intents: " + as_text(item.get("allowed_operation_intents", [])),
            "required_slots: " + as_text(item.get("required_slots", [])),
            "optional_slots: " + as_text(item.get("optional_slots", [])),
            "sample_questions: " + as_text(item.get("sample_questions", [])),
            "risk_notes: " + as_text(item.get("risk_notes", [])),
        )
        cards.append(
            make_card(
                card_id=f"business_intent:{item['business_intent_id']}",
                card_type="business_intent",
                title=item.get("business_intent_name") or item["business_intent_id"],
                text=text,
                metadata={
                    "business_intent_id": item["business_intent_id"],
                    "allowed_methods": item.get("allowed_methods", []),
                    "related_classes": item.get("related_classes", []),
                },
                source_file=str(path),
            )
        )
    return cards


def build_operation_intent_cards(task_ontology_dir):
    path = Path(task_ontology_dir) / "operation_intents.json"
    items = load_json(path)["operation_intents"]
    cards = []
    for item in items:
        text = join_text(
            item.get("operation_intent_id"),
            item.get("description"),
            "source_refs: " + as_text(item.get("source_refs", [])),
        )
        cards.append(
            make_card(
                card_id=f"operation_intent:{item['operation_intent_id']}",
                card_type="operation_intent",
                title=item["operation_intent_id"],
                text=text,
                metadata={
                    "operation_intent_id": item["operation_intent_id"],
                },
                source_file=str(path),
            )
        )
    return cards


def build_slot_cards(task_ontology_dir):
    path = Path(task_ontology_dir) / "task_slots.json"
    items = load_json(path)["task_slots"]
    cards = []
    for item in items:
        text = join_text(
            item.get("slot_id"),
            item.get("description"),
            "value_type: " + as_text(item.get("value_type")),
            "required_by_methods: " + as_text(item.get("required_by_methods", [])),
            "optional_by_methods: " + as_text(item.get("optional_by_methods", [])),
            "clarify_if_missing_for_operations: " + as_text(item.get("clarify_if_missing_for_operations", [])),
        )
        cards.append(
            make_card(
                card_id=f"task_slot:{item['slot_id']}",
                card_type="task_slot",
                title=item["slot_id"],
                text=text,
                metadata={
                    "slot_id": item["slot_id"],
                    "value_type": item.get("value_type", "unknown"),
                    "source_methods": item.get("source_methods", []),
                },
                source_file=str(path),
            )
        )
    return cards


def build_value_cards(task_ontology_dir):
    path = Path(task_ontology_dir) / "task_values.json"
    items = load_json(path)["task_values"]
    cards = []
    for item in items:
        text = join_text(
            item.get("value"),
            item.get("description"),
            "value_type: " + as_text(item.get("value_type")),
        )
        card_id = f"task_value:{item.get('value_type')}:{item.get('value')}"
        cards.append(
            make_card(
                card_id=card_id,
                card_type="task_value",
                title=as_text(item.get("value")),
                text=text,
                metadata={
                    "value": item.get("value"),
                    "value_type": item.get("value_type"),
                },
                source_file=str(path),
            )
        )
    return cards


def build_class_cards(object_ontology_dir):
    path = Path(object_ontology_dir) / "ontology_classes.json"
    items = load_json(path)["classes"]
    derived_path = Path(object_ontology_dir) / "ontology_derived_classes.json"
    derived_items = []
    if derived_path.exists():
        derived_items = load_json(derived_path)["derived_classes"]
    cards = []
    for item in items + derived_items:
        text = join_text(
            item.get("class_id"),
            item.get("class_name"),
            item.get("description"),
            "source_table: " + as_text(item.get("source_table")),
            "source_tables: " + as_text(item.get("source_tables", [])),
            "source_classes: " + as_text(item.get("source_classes", [])),
            "business_domain: " + as_text(item.get("business_domain")),
            "class_role: " + as_text(item.get("class_role")),
            "default_display_property: " + as_text(item.get("default_display_property")),
            "primary_key_columns: " + as_text(item.get("primary_key_columns", [])),
            "semantic_rule: " + as_text(item.get("semantic_rule")),
        )
        cards.append(
            make_card(
                card_id=f"class:{item['class_id']}",
                card_type="class",
                title=item["class_id"],
                text=text,
                metadata={
                    "class_id": item["class_id"],
                    "source_table": item.get("source_table"),
                    "source_tables": item.get("source_tables", []),
                    "ontology_layer": item.get("ontology_layer", "base_class"),
                    "business_domain": item.get("business_domain"),
                },
                source_file=str(path),
            )
        )
    return cards


def build_property_cards(object_ontology_dir):
    path = Path(object_ontology_dir) / "ontology_properties.json"
    items = load_json(path)["properties"]
    cards = []
    for item in items:
        text = join_text(
            item.get("property_id"),
            item.get("property_name"),
            item.get("description"),
            "class_id: " + as_text(item.get("class_id")),
            "source_column: " + as_text(item.get("source_column")),
            "data_type: " + as_text(item.get("data_type")),
            "property_type: " + as_text(item.get("property_type")),
            "role_guess: " + as_text(item.get("role_guess")),
            "is_identifier: " + as_text(item.get("is_identifier")),
            "is_object_key: " + as_text(item.get("is_object_key")),
        )
        cards.append(
            make_card(
                card_id=f"property:{item['property_id']}",
                card_type="property",
                title=item["property_id"],
                text=text,
                metadata={
                    "property_id": item["property_id"],
                    "class_id": item.get("class_id"),
                    "source_column": item.get("source_column"),
                    "property_type": item.get("property_type"),
                },
                source_file=str(path),
            )
        )
    return cards


def build_method_cards(method_contract_dir):
    path = Path(method_contract_dir) / "method_contracts.json"
    items = load_json(path)["method_contracts"]
    cards = []
    for item in items:
        text = join_text(
            item.get("method_id"),
            item.get("description"),
            item.get("business_meaning"),
            "business_domain: " + as_text(item.get("business_domain")),
            "business_intent_ids: " + as_text(item.get("business_intent_ids", [])),
            "operation_intent: " + as_text(item.get("operation_intent")),
            "target_classes: " + as_text(item.get("target_classes", [])),
            "required_tables: " + as_text(item.get("required_tables", [])),
            "required_columns: " + as_text(item.get("required_columns", [])),
            "required_slots: " + as_text(item.get("required_slots", [])),
            "optional_slots: " + as_text(item.get("optional_slots", [])),
            "required_semantics: " + as_text(item.get("required_semantics", [])),
            "forbidden_semantics: " + as_text(item.get("forbidden_semantics", [])),
            "semantic_guardrails: " + as_text(item.get("semantic_guardrails", [])),
            "common_failure_modes: " + as_text(item.get("common_failure_modes", [])),
            "example_scenarios: " + as_text(item.get("example_scenarios", [])),
        )
        cards.append(
            make_card(
                card_id=f"method:{item['method_id']}",
                card_type="method",
                title=item["method_id"],
                text=text,
                metadata={
                    "method_id": item["method_id"],
                    "business_intent_ids": item.get("business_intent_ids", []),
                    "operation_intent": item.get("operation_intent"),
                    "target_classes": item.get("target_classes", []),
                },
                source_file=str(path),
            )
        )
    return cards


def build_policy_cards(semantic_policy_dir):
    path = Path(semantic_policy_dir) / "semantic_policies.json"
    items = load_json(path)["semantic_policies"]
    cards = []
    for item in items:
        text = join_text(
            item.get("policy_id"),
            item.get("policy_type"),
            item.get("statement"),
            item.get("normalized_statement"),
            item.get("audit_question"),
            item.get("failure_signature"),
            "enforcement_action: " + as_text(item.get("enforcement_action")),
            "severity: " + as_text(item.get("severity")),
            "applies_to_methods: " + as_text(item.get("applies_to_methods", [])),
            "source: " + as_text(item.get("source", {})),
        )
        cards.append(
            make_card(
                card_id=f"semantic_policy:{item['policy_id']}",
                card_type="semantic_policy",
                title=item["policy_id"],
                text=text,
                metadata={
                    "policy_id": item["policy_id"],
                    "policy_type": item.get("policy_type"),
                    "enforcement_action": item.get("enforcement_action"),
                    "severity": item.get("severity"),
                    "applies_to_methods": item.get("applies_to_methods", []),
                },
                source_file=str(path),
            )
        )
    return cards


def build_bm25_index(cards, k1=1.5, b=0.75):
    doc_freq = Counter()
    documents = []

    for card in cards:
        term_freq = Counter(card["tokens"])
        for term in term_freq:
            doc_freq[term] += 1
        documents.append(
            {
                "card_id": card["card_id"],
                "card_type": card["card_type"],
                "doc_len": len(card["tokens"]),
                "term_freq": dict(sorted(term_freq.items())),
            }
        )

    avg_doc_len = sum(item["doc_len"] for item in documents) / max(1, len(documents))
    return {
        "index_type": "bm25",
        "tokenizer": "unicode_word_lowercase_len_gt_1",
        "k1": k1,
        "b": b,
        "document_count": len(documents),
        "avg_doc_len": avg_doc_len,
        "doc_freq": dict(sorted(doc_freq.items())),
        "documents": documents,
    }


def bm25_score(query_tokens, document, doc_freq, document_count, avg_doc_len, k1, b):
    score = 0.0
    term_freq = document["term_freq"]
    doc_len = document["doc_len"]

    for token in query_tokens:
        if token not in term_freq:
            continue
        df = doc_freq.get(token, 0)
        idf = math.log(1 + (document_count - df + 0.5) / (df + 0.5))
        tf = term_freq[token]
        denominator = tf + k1 * (1 - b + b * doc_len / max(avg_doc_len, 1e-9))
        score += idf * (tf * (k1 + 1)) / denominator
    return score


def search_bm25(query, cards_by_id, bm25_index, top_k=8):
    query_tokens = tokenize(query)
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
        if score > 0:
            card = cards_by_id[document["card_id"]]
            scored.append(
                {
                    "card_id": card["card_id"],
                    "card_type": card["card_type"],
                    "title": card["title"],
                    "score": round(score, 6),
                    "metadata": card["metadata"],
                }
            )

    return sorted(scored, key=lambda item: item["score"], reverse=True)[:top_k]


def build_smoke_tests(cards, bm25_index):
    cards_by_id = {item["card_id"]: item for item in cards}
    queries = [
        "GMV Shopee tháng 9 không tính phí vận chuyển",
        "doanh thu thuần sau hoàn trả approved",
        "tồn kho khả dụng theo ngày snapshot",
        "top sản phẩm bán chạy theo số lượng",
        "conversion rate website",
        "xóa toàn bộ đơn hàng",
    ]
    return [
        {
            "query": query,
            "top_results": search_bm25(query, cards_by_id, bm25_index, top_k=8),
        }
        for query in queries
    ]


def audit_retrieval_cards(cards):
    findings = []
    card_ids = [item["card_id"] for item in cards]
    duplicate_ids = sorted([card_id for card_id, count in Counter(card_ids).items() if count > 1])

    for card_id in duplicate_ids:
        findings.append(
            {
                "severity": "HIGH",
                "category": "duplicate_card_id",
                "card_id": card_id,
                "message": "Duplicate retrieval card id.",
            }
        )

    for card in cards:
        if not card.get("text", "").strip():
            findings.append(
                {
                    "severity": "HIGH",
                    "category": "empty_card_text",
                    "card_id": card["card_id"],
                    "message": "Retrieval card has empty text.",
                }
            )
        if not card.get("tokens"):
            findings.append(
                {
                    "severity": "MEDIUM",
                    "category": "empty_card_tokens",
                    "card_id": card["card_id"],
                    "message": "Retrieval card has no tokens after tokenization.",
                }
            )

    return findings


def build_retrieval_index_artifacts(
    database_id,
    object_ontology_dir,
    task_ontology_dir,
    method_contract_dir,
    semantic_policy_dir,
    output_dir,
):
    output_dir = Path(output_dir)

    cards = []
    cards.extend(build_business_intent_cards(task_ontology_dir))
    cards.extend(build_operation_intent_cards(task_ontology_dir))
    cards.extend(build_slot_cards(task_ontology_dir))
    cards.extend(build_value_cards(task_ontology_dir))
    cards.extend(build_class_cards(object_ontology_dir))
    cards.extend(build_property_cards(object_ontology_dir))
    cards.extend(build_method_cards(method_contract_dir))
    cards.extend(build_policy_cards(semantic_policy_dir))

    cards = sorted(cards, key=lambda item: (item["card_type"], item["card_id"]))
    card_type_counts = Counter(item["card_type"] for item in cards)
    bm25_index = build_bm25_index(cards)
    smoke_tests = build_smoke_tests(cards, bm25_index)
    audit_findings = audit_retrieval_cards(cards)
    readiness_status = "READY" if not [item for item in audit_findings if item["severity"] == "HIGH"] else "NOT_READY"

    cards_for_storage = [
        {
            "card_id": item["card_id"],
            "card_type": item["card_type"],
            "title": item["title"],
            "text": item["text"],
            "metadata": item["metadata"],
            "source_file": item["source_file"],
        }
        for item in cards
    ]

    manifest = {
        "database_id": database_id,
        "artifact_type": "retrieval_indexes",
        "version": "v01",
        "construction_mode": "bm25_text_cards",
        "input_object_ontology_dir": str(object_ontology_dir),
        "input_task_ontology_dir": str(task_ontology_dir),
        "input_method_contract_dir": str(method_contract_dir),
        "input_semantic_policy_dir": str(semantic_policy_dir),
        "readiness_status": readiness_status,
        "output_files": {
            "retrieval_cards": str(output_dir / "retrieval_cards.json"),
            "bm25_index": str(output_dir / "bm25_index.json"),
            "retrieval_smoke_tests": str(output_dir / "retrieval_smoke_tests.json"),
            "retrieval_audit": str(output_dir / "retrieval_audit.json"),
        },
        "counts": {
            "cards": len(cards),
            "cards_by_type": dict(sorted(card_type_counts.items())),
            "vocab_size": len(bm25_index["doc_freq"]),
            "audit_findings": len(audit_findings),
            "high_findings": len([item for item in audit_findings if item["severity"] == "HIGH"]),
            "medium_findings": len([item for item in audit_findings if item["severity"] == "MEDIUM"]),
        },
    }

    save_json({"database_id": database_id, "retrieval_cards": cards_for_storage}, output_dir / "retrieval_cards.json")
    save_json({"database_id": database_id, "bm25_index": bm25_index}, output_dir / "bm25_index.json")
    save_json({"database_id": database_id, "smoke_tests": smoke_tests}, output_dir / "retrieval_smoke_tests.json")
    save_json({"database_id": database_id, "audit_findings": audit_findings}, output_dir / "retrieval_audit.json")
    save_json(manifest, output_dir / "retrieval_manifest.json")
    return manifest


def build_parser():
    parser = argparse.ArgumentParser(
        description="Build BM25 retrieval cards/indexes from offline ontology artifacts."
    )
    parser.add_argument("--database-id", required=True)
    parser.add_argument("--object-ontology-dir", required=True)
    parser.add_argument("--task-ontology-dir", required=True)
    parser.add_argument("--method-contract-dir", required=True)
    parser.add_argument("--semantic-policy-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    manifest = build_retrieval_index_artifacts(
        database_id=args.database_id,
        object_ontology_dir=Path(args.object_ontology_dir),
        task_ontology_dir=Path(args.task_ontology_dir),
        method_contract_dir=Path(args.method_contract_dir),
        semantic_policy_dir=Path(args.semantic_policy_dir),
        output_dir=Path(args.output_dir),
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
