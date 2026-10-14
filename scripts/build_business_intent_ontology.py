import argparse
import csv
import html
import json
import zipfile
from pathlib import Path


INTENT_RENAMES = {
    "STORE_PERFORMANCE": "STORE_ANALYTICS",
    "CHANNEL_PERFORMANCE": "CHANNEL_ANALYTICS",
}


INTENT_NAME_OVERRIDES = {
    "STORE_ANALYTICS": "Phân tích cửa hàng",
    "CHANNEL_ANALYTICS": "Phân tích kênh",
}


INTENT_DEFINITION_OVERRIDES = {
    "PRODUCT_DISCOVERY": {
        "taxonomy_review_decision": "CLARIFY_DEFINITION",
        "taxonomy_review_note": "SKU/catalog là đầu ra chính. Nếu promotion/supplier chỉ là điều kiện lọc thì vẫn giữ PRODUCT_DISCOVERY.",
    },
    "PROMOTION_PROGRAM": {
        "taxonomy_review_decision": "CLARIFY_DEFINITION",
        "taxonomy_review_note": "Promotion/campaign là đầu ra chính. Nếu câu hỏi trả danh sách SKU có promotion thì chuyển sang PRODUCT_DISCOVERY.",
    },
    "SUPPLIER_NETWORK": {
        "taxonomy_review_decision": "CLARIFY_DEFINITION",
        "taxonomy_review_note": "Dùng khi đầu ra chính là supplier hoặc quan hệ cung ứng; không dùng cho catalog SKU thông thường.",
    },
    "ORDER_LIFECYCLE": {
        "taxonomy_review_decision": "CLARIFY_DEFINITION",
        "taxonomy_review_note": "Dùng cho đơn hàng/trạng thái đơn. Nếu phân tích theo từng Channel thì chuyển sang CHANNEL_ANALYTICS.",
    },
    "PRODUCT_SALES": {
        "taxonomy_review_decision": "CLARIFY_DEFINITION",
        "taxonomy_review_note": "Dùng cho kết quả bán thực tế theo SKU/dòng hàng; không dùng cho catalog SKU.",
    },
    "REVENUE_METRICS": {
        "taxonomy_review_decision": "CLARIFY_DEFINITION",
        "taxonomy_review_note": "Dùng cho metric doanh thu cấp hệ thống hoặc filter một kênh cụ thể. Nếu GROUP BY từng Channel thì dùng CHANNEL_ANALYTICS.",
    },
    "REGIONAL_COVERAGE": {
        "taxonomy_review_decision": "CLARIFY_DEFINITION",
        "taxonomy_review_note": "Dùng khi Region là đơn vị phân nhóm/xếp hạng. Nếu đầu ra là danh sách Store/Customer cụ thể thì dùng intent tương ứng.",
    },
    "STORE_ANALYTICS": {
        "taxonomy_review_decision": "RENAME_AND_CLARIFY_SCOPE",
        "answer_contract": "Cửa hàng là thực thể được tra cứu, thống kê, so sánh hoặc xếp hạng.",
        "include_when": "Danh sách cửa hàng, số đơn theo cửa hàng, top/rank store theo đơn hoặc doanh thu.",
        "exclude_when": "Metric doanh thu toàn hệ thống thuộc REVENUE_METRICS; phân tích theo kênh thuộc CHANNEL_ANALYTICS.",
        "taxonomy_review_note": "Đổi tên từ STORE_PERFORMANCE vì không phải câu hỏi store nào cũng là performance/ranking.",
    },
    "CHANNEL_ANALYTICS": {
        "taxonomy_review_decision": "RENAME_AND_CLARIFY_SCOPE",
        "answer_contract": "Kênh bán là thực thể được thống kê, so sánh hoặc xếp hạng.",
        "include_when": "Số đơn, GMV, chat, so sánh hoặc ranking theo từng channel.",
        "exclude_when": "Tổng metric toàn hệ thống hoặc filter một channel cụ thể thuộc intent metric gốc.",
        "taxonomy_review_note": "Đổi tên từ CHANNEL_PERFORMANCE; GROUP BY Channel thuộc CHANNEL_ANALYTICS dù có ORDER BY hay không.",
    },
}


SCENARIO_INTENT_OVERRIDES = {
    "BI-04-03": "PRODUCT_DISCOVERY",
    "BI-14-04": "CHANNEL_ANALYTICS",
}


METHOD_OUTPUT_REVIEW_SCENARIOS = {
    "BI-07-01": "Hỏi COUNT khách VIP nhưng method hiện tại thiên về listCustomersBySegment.",
    "BI-13-03": "Hỏi dòng/SKU có line-net lớn nhất nhưng method hiện tại trả scalar tổng.",
    "BI-17-04": "Hỏi danh sách pending Return nhưng method hiện tại trả count.",
    "BI-21-02": "Hỏi danh sách ticket High chưa resolve nhưng method hiện tại trả count.",
    "BI-23-04": "Hỏi số supplier theo Region nhưng method hiện tại trả list theo một region.",
}


METHOD_GAP_SCENARIOS = {
    "BI-03-01": "Cần trả cây category 3 cấp; thiếu method binding cụ thể.",
    "BI-04-01": "Cần liệt kê mã khuyến mãi; thiếu method binding cụ thể.",
    "BI-06-04": "Cần SKU có >=2 suppliers; thiếu method binding cụ thể.",
    "BI-07-03": "Cần khách theo vùng; thiếu method binding cụ thể.",
    "BI-14-02": "Cần AOV paid orders; thiếu method binding cụ thể.",
    "BI-14-04": "Cần GMV theo từng channel; thiếu method binding rõ GMV != gross.",
    "BI-15-04": "Cần top payment_method; thiếu method binding cụ thể.",
    "BI-23-03": "Cần rank Region by customer count; thiếu method binding cụ thể.",
}


BOUNDARY_INTENT_OVERRIDES = {
    ("BND-01", "intent_a"): "CHANNEL_ANALYTICS",
    ("BND-19", "intent_a"): "CHANNEL_ANALYTICS",
}


BOUNDARY_REVIEW_NOTES = {
    "BND-01": {
        "review_status": "SAME_INTENT_INVARIANCE_OR_REDESIGN_REQUIRED",
        "review_note": "A và B đều thuộc CHANNEL_ANALYTICS sau review. Nếu cần boundary khác intent, thay A thành 'Tổng GMV tháng 9 toàn hệ thống?' -> REVENUE_METRICS.",
    },
    "BND-19": {
        "review_status": "SAME_INTENT_INVARIANCE_OR_REDESIGN_REQUIRED",
        "review_note": "A và B đều thuộc CHANNEL_ANALYTICS sau review. Nếu cần boundary khác intent, thay A thành 'Tổng số đơn toàn hệ thống?' -> ORDER_LIFECYCLE.",
    },
}


ADDITIONAL_BOUNDARY_TESTS = [
    ("N-01", "GMV toàn hệ thống tháng 9?", "REVENUE_METRICS", "GMV theo từng kênh tháng 9?", "CHANNEL_ANALYTICS"),
    ("N-02", "GMV từng kênh tháng 9?", "CHANNEL_ANALYTICS", "Xếp hạng kênh theo GMV tháng 9?", "CHANNEL_ANALYTICS"),
    ("N-03", "Có bao nhiêu đơn toàn hệ thống?", "ORDER_LIFECYCLE", "Có bao nhiêu đơn theo từng kênh?", "CHANNEL_ANALYTICS"),
    ("N-04", "Đơn theo từng kênh tháng 9?", "CHANNEL_ANALYTICS", "Kênh nào có nhiều đơn nhất tháng 9?", "CHANNEL_ANALYTICS"),
    ("N-05", "Cho biết tất cả chương trình khuyến mãi còn hiệu lực.", "PROMOTION_PROGRAM", "Liệt kê SKU có promotion chính đang hiệu lực.", "PRODUCT_DISCOVERY"),
    ("N-06", "Các SKU đang có hàng trong catalog?", "PRODUCT_DISCOVERY", "SKU nào được cung cấp bởi >=2 nhà cung cấp?", "SUPPLIER_NETWORK"),
    ("N-07", "Tổng giá trị dòng hàng theo từng SKU?", "PRODUCT_SALES", "Tổng GMV các đơn đã thanh toán?", "REVENUE_METRICS"),
    ("N-08", "Có bao nhiêu cửa hàng theo vùng?", "REGIONAL_COVERAGE", "Danh sách cửa hàng miền Bắc?", "STORE_ANALYTICS"),
    ("N-09", "Top cửa hàng theo số đơn?", "STORE_ANALYTICS", "Số đơn theo từng cửa hàng?", "STORE_ANALYTICS"),
    ("N-10", "Tổng giá trị payment success?", "PAYMENT_OPERATIONS", "GMV đơn đã thanh toán là bao nhiêu?", "REVENUE_METRICS"),
]


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_json(data, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def save_csv(rows, path, fieldnames):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def rename_intent_id(intent_id):
    return INTENT_RENAMES.get(intent_id, intent_id)


def normalize_intent_value(value):
    if isinstance(value, str):
        result = value
        for old, new in INTENT_RENAMES.items():
            result = result.replace(old, new)
        return result
    if isinstance(value, list):
        return [normalize_intent_value(item) for item in value]
    if isinstance(value, dict):
        return {key: normalize_intent_value(item) for key, item in value.items()}
    return value


def apply_intent_catalog_review(business_intents):
    reviewed = normalize_intent_value(business_intents)
    for intent in reviewed["business_intents"]:
        intent_id = intent["intent_id"]
        intent["intent_id"] = rename_intent_id(intent_id)
        if intent["intent_id"] in INTENT_NAME_OVERRIDES:
            intent["intent_name_vi"] = INTENT_NAME_OVERRIDES[intent["intent_id"]]

        override = INTENT_DEFINITION_OVERRIDES.get(intent["intent_id"], {})
        for key, value in override.items():
            intent[key] = value

    reviewed["version"] = "v01_approved_with_changes"
    reviewed["review_status"] = "TAXONOMY_V01_APPROVED_WITH_CHANGES"
    reviewed["review_policy"] = {
        "atomic_intents": 23,
        "composite_intents": 1,
        "classifier_ground_truth_status": "NOT_FROZEN_UNTIL_REVIEW_CHANGES_APPLIED_AND_AUDITED",
        "primary_routing_rule": "One fully specified supported question maps to exactly one business intent; dimensions, filters, ordering and limits are query parameters.",
    }
    reviewed["label_policy"]["contract_version"] = "v01-approved-with-changes"
    reviewed["label_policy"]["critical_distinctions"] = [
        "GROUP BY Channel hoặc ranking Channel theo GMV/order/chat -> CHANNEL_ANALYTICS.",
        "GROUP BY Store hoặc ranking Store theo order/revenue -> STORE_ANALYTICS.",
        "Tổng metric toàn hệ thống hoặc filter một channel cụ thể -> metric intent gốc, ví dụ REVENUE_METRICS.",
        "SKU catalog -> PRODUCT_DISCOVERY; SKU theo bán thực tế -> PRODUCT_SALES; SKU theo supplier network -> SUPPLIER_NETWORK.",
        "Payment event grain -> PAYMENT_OPERATIONS; paid-order grain -> REVENUE_METRICS.",
        "Current customer address -> DELIVERY_ADDRESS; shipment address snapshot -> SHIPPING_LOGISTICS.",
    ]
    return reviewed


def intent_lookup(reviewed_business_intents):
    return {
        item["intent_id"]: item
        for item in reviewed_business_intents["business_intents"]
    }


def sync_scenario_to_intent(scenario, intent):
    scenario["gold_primary_output"] = intent.get("answer_contract")
    scenario["candidate_methods"] = intent.get("candidate_methods", [])
    scenario["grounded_base_classes"] = intent.get("candidate_base_classes", [])
    scenario["grounded_derived_classes"] = intent.get("candidate_derived_classes", [])
    scenario["grounded_property_ids"] = intent.get("grounded_property_ids", [])
    scenario["grounded_relation_ids"] = intent.get("grounded_relation_ids", [])
    return scenario


def apply_scenario_review(intent_scenarios, reviewed_business_intents):
    reviewed = normalize_intent_value(intent_scenarios)
    intents_by_id = intent_lookup(reviewed_business_intents)
    findings = []

    for scenario in reviewed["scenarios"]:
        scenario_id = scenario["scenario_id"]
        scenario["expected_intent_id"] = rename_intent_id(scenario.get("expected_intent_id", ""))

        if scenario_id in SCENARIO_INTENT_OVERRIDES:
            new_intent_id = SCENARIO_INTENT_OVERRIDES[scenario_id]
            scenario["expected_intent_id"] = new_intent_id
            scenario["taxonomy_review_action"] = "INTENT_LABEL_CORRECTED"
            scenario["taxonomy_review_note"] = f"Intent label corrected to {new_intent_id} by independent review."
            sync_scenario_to_intent(scenario, intents_by_id[new_intent_id])
            findings.append(
                {
                    "scenario_id": scenario_id,
                    "finding_type": "INTENT_LABEL_CORRECTED",
                    "new_intent_id": new_intent_id,
                    "severity": "REVIEW_APPLIED",
                }
            )

        if scenario_id in METHOD_OUTPUT_REVIEW_SCENARIOS:
            scenario["method_review_status"] = "METHOD_OUTPUT_REVIEW_REQUIRED"
            scenario["method_review_note"] = METHOD_OUTPUT_REVIEW_SCENARIOS[scenario_id]
            findings.append(
                {
                    "scenario_id": scenario_id,
                    "finding_type": "METHOD_OUTPUT_REVIEW_REQUIRED",
                    "expected_intent_id": scenario["expected_intent_id"],
                    "severity": "REVIEW_REQUIRED",
                    "note": METHOD_OUTPUT_REVIEW_SCENARIOS[scenario_id],
                }
            )

        if scenario_id in METHOD_GAP_SCENARIOS:
            scenario["method_review_status"] = "METHOD_CONTRACT_GAP"
            scenario["method_review_note"] = METHOD_GAP_SCENARIOS[scenario_id]
            findings.append(
                {
                    "scenario_id": scenario_id,
                    "finding_type": "METHOD_CONTRACT_GAP",
                    "expected_intent_id": scenario["expected_intent_id"],
                    "severity": "REVIEW_REQUIRED",
                    "note": METHOD_GAP_SCENARIOS[scenario_id],
                }
            )

    reviewed["version"] = "v01_approved_with_changes"
    reviewed["scenario_count"] = len(reviewed["scenarios"])
    return reviewed, findings


def apply_boundary_review(boundary_tests):
    reviewed = normalize_intent_value(boundary_tests)
    for boundary in reviewed["boundaries"]:
        boundary_id = boundary["boundary_id"]
        boundary["intent_a"] = rename_intent_id(boundary["intent_a"])
        boundary["intent_b"] = rename_intent_id(boundary["intent_b"])
        for field in ["intent_a", "intent_b"]:
            if (boundary_id, field) in BOUNDARY_INTENT_OVERRIDES:
                boundary[field] = BOUNDARY_INTENT_OVERRIDES[(boundary_id, field)]
                boundary["taxonomy_review_action"] = "BOUNDARY_LABEL_CORRECTED"
        if boundary_id in BOUNDARY_REVIEW_NOTES:
            boundary.update(BOUNDARY_REVIEW_NOTES[boundary_id])

    reviewed["version"] = "v01_approved_with_changes"
    reviewed["additional_boundary_tests"] = [
        {
            "boundary_id": boundary_id,
            "question_a": question_a,
            "intent_a": intent_a,
            "question_b": question_b,
            "intent_b": intent_b,
        }
        for boundary_id, question_a, intent_a, question_b, intent_b in ADDITIONAL_BOUNDARY_TESTS
    ]
    return reviewed


def load_mapping_csv(path):
    rows = []
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            normalized_row = {key.lstrip("\ufeff"): value for key, value in row.items()}
            rows.append(normalized_row)
    return rows


def apply_mapping_review(mapping_rows, reviewed_business_intents):
    rows_by_intent = {row["intent_id"]: normalize_intent_value(row) for row in mapping_rows}
    reviewed_rows = []
    for intent in reviewed_business_intents["business_intents"]:
        intent_id = intent["intent_id"]
        row = rows_by_intent.get(intent_id)
        if not row:
            old_ids = [old for old, new in INTENT_RENAMES.items() if new == intent_id]
            row = rows_by_intent.get(old_ids[0]) if old_ids else None
        if row:
            row = normalize_intent_value(row)
            row["intent_id"] = intent_id
        else:
            row = {
                "intent_id": intent_id,
                "answer_contract": intent.get("answer_contract", ""),
                "base_classes": ", ".join(intent.get("candidate_base_classes", [])),
                "derived_classes": ", ".join(intent.get("candidate_derived_classes", [])),
                "candidate_methods": ", ".join(intent.get("candidate_methods", [])),
                "property_ids": ", ".join(intent.get("grounded_property_ids", [])),
                "relation_ids": ", ".join(intent.get("grounded_relation_ids", [])),
                "execution_status": intent.get("execution_status", ""),
            }
        reviewed_rows.append(row)
    return reviewed_rows


def flatten_intent_catalog(business_intents):
    rows = []
    for item in business_intents["business_intents"]:
        rows.append(
            {
                "intent_id": item["intent_id"],
                "intent_name_vi": item.get("intent_name_vi", ""),
                "intent_kind": item.get("intent_kind", ""),
                "answer_contract": item.get("answer_contract", ""),
                "include_when": item.get("include_when", ""),
                "exclude_when": item.get("exclude_when", ""),
                "candidate_base_classes": ", ".join(item.get("candidate_base_classes", [])),
                "candidate_derived_classes": ", ".join(item.get("candidate_derived_classes", [])),
                "candidate_methods": ", ".join(item.get("candidate_methods", [])),
                "taxonomy_review_decision": item.get("taxonomy_review_decision", "KEEP"),
                "taxonomy_review_note": item.get("taxonomy_review_note", ""),
            }
        )
    return rows


def flatten_scenarios(intent_scenarios):
    rows = []
    for item in intent_scenarios["scenarios"]:
        rows.append(
            {
                "scenario_id": item["scenario_id"],
                "question": item.get("question", ""),
                "expected_action": item.get("expected_action", ""),
                "expected_intent_id": item.get("expected_intent_id", ""),
                "gold_method_id": item.get("gold_method_id", ""),
                "gold_primary_output": item.get("gold_primary_output", ""),
                "execution_readiness": item.get("execution_readiness", ""),
                "taxonomy_review_action": item.get("taxonomy_review_action", ""),
                "method_review_status": item.get("method_review_status", ""),
                "method_review_note": item.get("method_review_note", ""),
            }
        )
    return rows


def flatten_boundaries(boundary_tests):
    rows = []
    for item in boundary_tests["boundaries"]:
        rows.append(
            {
                "boundary_id": item["boundary_id"],
                "question_a": item.get("question_a", ""),
                "intent_a": item.get("intent_a", ""),
                "question_b": item.get("question_b", ""),
                "intent_b": item.get("intent_b", ""),
                "discriminator_vi": item.get("discriminator_vi", ""),
                "taxonomy_review_action": item.get("taxonomy_review_action", ""),
                "review_status": item.get("review_status", ""),
                "review_note": item.get("review_note", ""),
            }
        )
    return rows


def flatten_additional_boundaries(boundary_tests):
    return boundary_tests.get("additional_boundary_tests", [])


def column_letter(column_index):
    result = ""
    while column_index:
        column_index, remainder = divmod(column_index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def sheet_xml(rows, fieldnames):
    body = []
    all_rows = [fieldnames] + [[row.get(field, "") for field in fieldnames] for row in rows]
    for row_index, row_values in enumerate(all_rows, start=1):
        cells = []
        for column_index, value in enumerate(row_values, start=1):
            ref = f"{column_letter(column_index)}{row_index}"
            value = "" if value is None else str(value)
            cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{html.escape(value)}</t></is></c>')
        body.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    {"".join(body)}
  </sheetData>
</worksheet>'''


def workbook_xml(sheet_names):
    sheets = []
    for idx, name in enumerate(sheet_names, start=1):
        sheets.append(f'<sheet name="{html.escape(name)}" sheetId="{idx}" r:id="rId{idx}"/>')
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>{"".join(sheets)}</sheets>
</workbook>'''


def workbook_rels_xml(sheet_count):
    rels = []
    for idx in range(1, sheet_count + 1):
        rels.append(
            f'<Relationship Id="rId{idx}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{idx}.xml"/>'
        )
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  {"".join(rels)}
</Relationships>'''


def content_types_xml(sheet_count):
    overrides = [
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    ]
    for idx in range(1, sheet_count + 1):
        overrides.append(
            f'<Override PartName="/xl/worksheets/sheet{idx}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  {"".join(overrides)}
</Types>'''


def root_rels_xml():
    return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>'''


def save_xlsx(sheets, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet_names = [name for name, _, _ in sheets]
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types_xml(len(sheets)))
        zf.writestr("_rels/.rels", root_rels_xml())
        zf.writestr("xl/workbook.xml", workbook_xml(sheet_names))
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml(len(sheets)))
        for idx, (_, rows, fieldnames) in enumerate(sheets, start=1):
            zf.writestr(f"xl/worksheets/sheet{idx}.xml", sheet_xml(rows, fieldnames))


def load_object_ontology(object_ontology_dir):
    root = Path(object_ontology_dir)
    return {
        "base_classes": {item["class_id"] for item in load_json(root / "ontology_classes.json")["classes"]},
        "derived_classes": {item["class_id"] for item in load_json(root / "ontology_derived_classes.json")["derived_classes"]},
        "properties": {item["property_id"] for item in load_json(root / "ontology_properties.json")["properties"]},
        "relations": {item["relation_id"] for item in load_json(root / "ontology_relations.json")["relations"]},
        "methods": {item["method_id"] for item in load_json(root / "ontology_class_methods.json")["class_methods"]},
    }


def audit_business_intents(business_intents, intent_scenarios, boundary_tests, object_ontology, method_findings):
    high_findings = []
    review_findings = []

    intent_ids = [item["intent_id"] for item in business_intents["business_intents"]]
    duplicate_intents = sorted({item for item in intent_ids if intent_ids.count(item) > 1})
    if duplicate_intents:
        high_findings.append({"category": "duplicate_intent_id", "intent_ids": duplicate_intents})

    if any(old in intent_ids for old in INTENT_RENAMES):
        high_findings.append({"category": "old_intent_id_not_fully_renamed", "old_intents": sorted(set(INTENT_RENAMES) & set(intent_ids))})

    valid_intents = set(intent_ids) | {"CLARIFY", "UNSUPPORTED", "REFUSE"}
    for scenario in intent_scenarios["scenarios"]:
        expected_intent_id = scenario.get("expected_intent_id")
        if scenario.get("expected_action") == "ROUTE_INTENT" and expected_intent_id not in valid_intents:
            high_findings.append(
                {
                    "category": "scenario_unknown_intent",
                    "scenario_id": scenario["scenario_id"],
                    "expected_intent_id": expected_intent_id,
                }
            )

    for boundary in boundary_tests["boundaries"]:
        if boundary.get("intent_a") not in valid_intents or boundary.get("intent_b") not in valid_intents:
            high_findings.append(
                {
                    "category": "boundary_unknown_intent",
                    "boundary_id": boundary["boundary_id"],
                    "intent_a": boundary.get("intent_a"),
                    "intent_b": boundary.get("intent_b"),
                }
            )
        if boundary.get("intent_a") == boundary.get("intent_b"):
            review_findings.append(
                {
                    "category": "same_intent_boundary",
                    "boundary_id": boundary["boundary_id"],
                    "intent": boundary.get("intent_a"),
                    "review_status": boundary.get("review_status", "CHECK_IF_INVARIANCE_TEST"),
                }
            )

    referenced_base = set()
    referenced_derived = set()
    referenced_properties = set()
    referenced_relations = set()
    referenced_methods = set()
    for intent in business_intents["business_intents"]:
        referenced_base.update(intent.get("candidate_base_classes", []))
        referenced_derived.update(intent.get("candidate_derived_classes", []))
        referenced_properties.update(intent.get("grounded_property_ids", []))
        referenced_relations.update(intent.get("grounded_relation_ids", []))
        referenced_methods.update(intent.get("candidate_methods", []))

    missing_base = sorted(referenced_base - object_ontology["base_classes"])
    missing_derived = sorted(referenced_derived - object_ontology["derived_classes"])
    missing_properties = sorted(referenced_properties - object_ontology["properties"])
    missing_relations = sorted(referenced_relations - object_ontology["relations"])
    missing_methods = sorted(referenced_methods - object_ontology["methods"])
    for category, values in [
        ("missing_base_classes", missing_base),
        ("missing_derived_classes", missing_derived),
        ("missing_properties", missing_properties),
        ("missing_relations", missing_relations),
    ]:
        if values:
            high_findings.append({"category": category, "values": values})

    if missing_methods:
        review_findings.append(
            {
                "category": "method_references_not_in_base_class_methods",
                "count": len(missing_methods),
                "note": "Method references are proposal-level until method contracts are approved.",
                "sample": missing_methods[:20],
            }
        )

    review_findings.extend(method_findings)
    counts = {
        "business_intents": len(intent_ids),
        "atomic_intents": len([item for item in business_intents["business_intents"] if item.get("intent_kind") == "ATOMIC"]),
        "composite_intents": len([item for item in business_intents["business_intents"] if item.get("intent_kind") == "COMPOSITE"]),
        "scenarios": len(intent_scenarios["scenarios"]),
        "boundary_tests": len(boundary_tests["boundaries"]),
        "additional_boundary_tests": len(boundary_tests.get("additional_boundary_tests", [])),
        "referenced_base_classes": len(referenced_base),
        "referenced_derived_classes": len(referenced_derived),
        "referenced_properties": len(referenced_properties),
        "referenced_relations": len(referenced_relations),
        "referenced_methods": len(referenced_methods),
        "missing_method_references": len(missing_methods),
        "high_findings": len(high_findings),
        "review_findings": len(review_findings),
    }
    return {
        "status": "STRUCTURAL_PASS_WITH_REVIEW" if not high_findings else "NOT_READY",
        "counts": counts,
        "high_findings": high_findings,
        "review_findings": review_findings,
    }


def build_business_intent_ontology(database_id, source_intent_dir, object_ontology_dir, output_dir):
    source_intent_dir = Path(source_intent_dir)
    output_dir = Path(output_dir)

    business_intents = load_json(source_intent_dir / "business_intents.json")
    intent_scenarios = load_json(source_intent_dir / "intent_scenarios.json")
    boundary_tests = load_json(source_intent_dir / "intent_boundary_tests.json")
    mapping_rows = load_mapping_csv(source_intent_dir / "intent_to_ontology_mapping.csv")
    object_ontology = load_object_ontology(object_ontology_dir)

    reviewed_business_intents = apply_intent_catalog_review(business_intents)
    reviewed_scenarios, method_findings = apply_scenario_review(intent_scenarios, reviewed_business_intents)
    reviewed_boundaries = apply_boundary_review(boundary_tests)
    reviewed_mapping_rows = apply_mapping_review(mapping_rows, reviewed_business_intents)
    audit = audit_business_intents(
        business_intents=reviewed_business_intents,
        intent_scenarios=reviewed_scenarios,
        boundary_tests=reviewed_boundaries,
        object_ontology=object_ontology,
        method_findings=method_findings,
    )

    intent_catalog_rows = flatten_intent_catalog(reviewed_business_intents)
    scenario_rows = flatten_scenarios(reviewed_scenarios)
    boundary_rows = flatten_boundaries(reviewed_boundaries)
    additional_boundary_rows = flatten_additional_boundaries(reviewed_boundaries)

    save_json(reviewed_business_intents, output_dir / "business_intents.json")
    save_json(reviewed_scenarios, output_dir / "intent_scenarios.json")
    save_json(reviewed_boundaries, output_dir / "intent_boundary_tests.json")
    save_json(audit, output_dir / "business_intent_ontology_audit.json")
    save_json({"database_id": database_id, "findings": method_findings}, output_dir / "intent_method_review_findings.json")

    save_csv(intent_catalog_rows, output_dir / "intent_catalog.csv", list(intent_catalog_rows[0].keys()))
    save_csv(scenario_rows, output_dir / "intent_scenarios.csv", list(scenario_rows[0].keys()))
    save_csv(boundary_rows, output_dir / "intent_boundary_tests.csv", list(boundary_rows[0].keys()))
    save_csv(additional_boundary_rows, output_dir / "additional_boundary_tests.csv", list(additional_boundary_rows[0].keys()))
    save_csv(reviewed_mapping_rows, output_dir / "intent_to_ontology_mapping.csv", list(reviewed_mapping_rows[0].keys()))

    save_xlsx(
        sheets=[
            ("Intent Catalog", intent_catalog_rows, list(intent_catalog_rows[0].keys())),
            ("Scenario Matrix", scenario_rows, list(scenario_rows[0].keys())),
            ("Boundary Tests", boundary_rows, list(boundary_rows[0].keys())),
            ("Additional Boundary", additional_boundary_rows, list(additional_boundary_rows[0].keys())),
            ("Method Review", method_findings, ["scenario_id", "finding_type", "expected_intent_id", "severity", "note", "new_intent_id"]),
        ],
        path=output_dir / "intent_scenarios.xlsx",
    )

    manifest = {
        "database_id": database_id,
        "artifact_type": "business_intent_ontology",
        "version": "v01_approved_with_changes",
        "construction_mode": "review_applied_deterministic",
        "input_source_intent_dir": str(source_intent_dir),
        "input_object_ontology_dir": str(object_ontology_dir),
        "readiness_status": audit["status"],
        "output_files": {
            "business_intents": str(output_dir / "business_intents.json"),
            "intent_scenarios": str(output_dir / "intent_scenarios.json"),
            "intent_scenarios_xlsx": str(output_dir / "intent_scenarios.xlsx"),
            "intent_boundary_tests": str(output_dir / "intent_boundary_tests.json"),
            "intent_to_ontology_mapping": str(output_dir / "intent_to_ontology_mapping.csv"),
            "business_intent_ontology_audit": str(output_dir / "business_intent_ontology_audit.json"),
            "intent_method_review_findings": str(output_dir / "intent_method_review_findings.json"),
        },
        "counts": audit["counts"],
    }
    save_json(manifest, output_dir / "business_intent_manifest.json")
    return manifest


def build_parser():
    parser = argparse.ArgumentParser(description="Build reviewed Business Intent Ontology from curated package and approved taxonomy review.")
    parser.add_argument("--database-id", required=True)
    parser.add_argument("--source-intent-dir", required=True)
    parser.add_argument("--object-ontology-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser


def main():
    args = build_parser().parse_args()
    manifest = build_business_intent_ontology(
        database_id=args.database_id,
        source_intent_dir=args.source_intent_dir,
        object_ontology_dir=args.object_ontology_dir,
        output_dir=args.output_dir,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
