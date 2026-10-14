# Omnichannel Retail | Business Intent Taxonomy v01.1

**Status:** `INTENT_LABELS_FROZEN_V01_1` / `ONTOLOGY_AUDIT_0_HIGH` / `METHOD_CONTRACTS_PENDING`

Từ bộ Business Intent v01 và review đã duyệt. **24 intents (23 atomic, 1 composite)**; **162 scenarios**; **20 contrasting boundaries**; **0 HIGH findings** trong audited referential/annotation scope. Có **53 câu hỏi nghiệp vụ atomic chưa có một Method gold với chữ ký hoàn toàn phù hợp**, được giữ nhãn và đánh dấu pending.

## Files bàn giao

| File | Nội dung |
|---|---|
| `business_intents_v01_1.json` | Taxonomy 24 Intent, answer-contract, include/exclude, candidate references |
| `intent_scenarios_v01_1.xlsx` | 10 sheet: Summary, Intent Catalog, Scenario Matrix, Boundary Tests, Method Binding Review, Policy Gates, Change Log, Original Label Fixes, Ontology Mapping, Additional Signature QA |
| `intent_scenarios_v01_1.json` | 162 scenario gán nhãn (machine-readable), có method binding status |
| `intent_boundary_tests_v01_1.json` | 20 contrasting pair tests, BND-01/19 đã sửa |
| `intent_ontology_audit_v01_1.json` | Audit cấu trúc và tham chiếu ontology/SQLite |
| `intent_to_ontology_mapping_v01_1.csv` | Intent → Class / Derived / Property / Method / Relation |
| `review_changes_v01_1.json` | Quyết định giữ/đổi tên/làm rõ, sửa nhãn và Method gaps |
| `additional_method_signature_qa_v01_1.json` | 39 signature mismatches bổ sung, có bằng chứng method signature |
| `taxonomy_freeze_review_v01_1.md` | Giải thích quyết định, kiểm định và giới hạn |
| `build_taxonomy_v01_1.py`, `validate_taxonomy_v01_1.py`, `test_taxonomy_v01_1.py` | Code và automated/negative tests |

## Sử dụng dữ liệu

- **Classifier training:** lấy các dòng `expected_action=ROUTE_INTENT` trong `intent_scenarios_v01_1.json`; gold class label = `expected_intent_id`. Không dùng boundary pair thuộc cả train và evaluation khi đánh giá tổng quát hóa; nên split theo nhóm paraphrase/semantic template.
- **Policy gate:** 24 dòng khác `ROUTE_INTENT` giữ action và `gate_reason_code` riêng; chúng không phải Intent của classifier atomic.
- **Routing:** `gold_method_id` chỉ có giá trị tham khảo khi `method_binding_status=METHOD_CANDIDATE_ONLY`; chưa chứng nhận executable. Nếu status `METHOD_CONTRACT_GAP` hay `METHOD_SIGNATURE_REVIEW_REQUIRED`, runtime phải dừng ở method-contract gate.
- **SQLite/ontology:** bản v01.1 tham chiếu Object Ontology v01 và SQLite v06 đã bàn giao. Không sử dụng ontology 17 bảng cũ.

## Tái kiểm định

Đặt cùng cấp ba thư mục `omnichannel_business_intent_v01_1`, `omnichannel_ontology_v01`, `omnichannel_retail_v06_final` và chạy:

```bash
python omnichannel_business_intent_v01_1/validate_taxonomy_v01_1.py \
  --input-dir omnichannel_business_intent_v01_1 \
  --ontology omnichannel_ontology_v01/ontology_inventory_v01.json \
  --sqlite omnichannel_retail_v06_final/omnichannel_retail.sqlite3

python -m unittest discover -v \
  -s omnichannel_business_intent_v01_1 -p 'test_taxonomy_v01_1.py'
```

Sử dụng `build_taxonomy_v01_1.py` để tái tạo từ v01 và `harden_additional_method_signatures.py` để áp dụng lượt QA chữ ký bổ sung. Không chạy builder lên chính thư mục đã đóng băng nếu không chủ ý rebuild.
