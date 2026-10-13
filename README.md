# Semantic Contract Text2SQL

Repo này lưu trữ hướng nghiên cứu và demo cho bài toán **Text2SQL có kiểm soát ngữ nghĩa**.

Ý tưởng chính:

```text
Natural Language
-> Ontology
-> Semantic Contract
-> SQL Planning
-> SQL Execution
-> Audit & Evaluation
```

## Vì sao cần repo này?

Trong Text2SQL, một câu SQL có thể:

- chạy được,
- trả về dữ liệu,
- không báo lỗi cú pháp,

nhưng vẫn **không đúng ý nghĩa câu hỏi**.

Ví dụ:

- Người dùng hỏi `tên ngắn`, nhưng SQL trả `full_name`.
- Người dùng hỏi `phường`, nhưng SQL đếm toàn bộ đơn vị cấp xã.
- Người dùng hỏi `ít nhất`, nhưng `INNER JOIN` làm mất các đối tượng có count bằng 0.
- Người dùng hỏi `GMV`, nhưng SQL lại tính doanh thu sau hoàn trả.

Repo này tập trung vào hướng:

> Dùng ontology và semantic contract để kiểm soát quá trình sinh SQL, thay vì chỉ kiểm tra SQL có chạy được hay không.

## Trạng thái hiện tại

Hiện tại repo đang ở giai đoạn:

```text
Phase 1: Ontology Consistency & Semantic Contract Audit
```

Kết quả chính:

- Đã có ontology hướng đối tượng cho database `vietnamese_admin_units`.
- Đã có runtime PoC để map câu hỏi sang method/template có kiểm soát.
- Đã có audit framework v01 và v01.1.
- Audit v01.1 phát hiện ontology hiện tại `NOT_READY` cho runtime v02.
- Đã bổ sung benchmark phức tạp hơn: `Omnichannel Retail Analytics`.

## Cấu trúc repo

```text
semantic-contract-text2sql/
│
├── landing/                         # Landing page static cho GitHub Pages
├── docs/                            # Tài liệu nghiên cứu và thiết kế
├── notebooks/                       # Notebook demo và audit
├── ontology/                        # Ontology artifacts
├── offline_artifacts/               # Template workspace offline cho từng database
├── benchmarks/                      # Dữ liệu benchmark và kết quả audit
├── src/semantic_contract_text2sql/   # Python package tối giản
├── tests/                           # Unit tests về sau
├── scripts/                         # Script chạy audit/evaluation
└── reports/                         # Báo cáo kết quả
```

## Notebooks chính

| Notebook | Nội dung |
|---|---|
| `01_object_ontology_runtime_demo_v01.ipynb` | PoC runtime: question -> method call -> SQL template |
| `02_semantic_contract_audit_baseline_v01.ipynb` | Audit v01 baseline |
| `03_semantic_contract_audit_hardened_v01_1.ipynb` | Audit v01.1 đã harden checker/guard |

## Case studies

### 1. Vietnamese Admin Units

Domain nhỏ, dễ kiểm chứng, dùng để xây nền:

- class,
- property,
- relation,
- method,
- SQL template,
- unsupported scope,
- semantic contract audit.

Kết quả audit v01.1:

```text
Audit execution: COMPLETED
Ontology readiness: NOT_READY
Test cases: 14
Passed: 14
Findings: 19 HIGH
Root-cause groups: 7
```

### 2. Omnichannel Retail Analytics

Domain phức tạp hơn, có:

- 17 bảng,
- 85 test cases,
- 70 gold SQL,
- GMV, net sales, refund, inventory, customer analysis,
- clarify / unsupported / refuse cases,
- negative examples.

Benchmark này dùng cho giai đoạn tiếp theo để kiểm tra khả năng mở rộng.

## Hướng nghiên cứu

Tên hướng:

```text
Ontology-based Semantic Contract Audit for Text2SQL
```

Mục tiêu:

- Tách rõ tầng database schema và tầng semantic ontology.
- Biểu diễn query intent có cấu trúc.
- Kiểm tra method, parameter, projection, filter, join, aggregation trước khi execute.
- Không để SQL chạy thành công nhưng âm thầm bỏ qua semantic intent.
- Tạo audit framework để phân loại lỗi và quyết định readiness.

## Cài đặt local

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Kiểm tra package:

```bash
python -m semantic_contract_text2sql --help
```

## Chạy nhanh audit summary

```bash
python scripts/print_audit_summary.py benchmarks/vietnamese_admin_units/results/audit_v01_1/audit_summary.json
```

## Khởi tạo offline workspace cho một database

Master plan offline nằm ở:

```text
docs/offline_artifact_master_plan.md
```

Tạo workspace chuẩn:

```bash
python scripts/init_offline_artifacts.py \
  --database-id vietnamese_admin_units \
  --output-root offline_artifacts
```

Validate cấu trúc:

```bash
python scripts/validate_offline_artifacts.py offline_artifacts/vietnamese_admin_units
```

Build database inventory từ SQLite/schema/spec:

```bash
python scripts/build_database_inventory.py \
  --database-id omnichannel_retail \
  --sqlite-path offline_artifacts/omnichannel_retail/00_sources/Text2SQL_Demo_Package_v01/text2sql_omnichannel_retail.sqlite \
  --schema-path offline_artifacts/omnichannel_retail/00_sources/Text2SQL_Demo_Package_v01/text2sql_schema.sql \
  --benchmark-spec-path offline_artifacts/omnichannel_retail/00_sources/Text2SQL_Demo_Package_v01/text2sql_benchmark_spec.json \
  --output-dir offline_artifacts/omnichannel_retail/01_database_inventory
```

Build object ontology hybrid:

```bash
python scripts/build_object_ontology_hybrid.py \
  --database-id omnichannel_retail \
  --inventory-dir offline_artifacts/omnichannel_retail/01_database_inventory \
  --output-dir offline_artifacts/omnichannel_retail/02_object_ontology \
  --use-llm
```

Build business task ontology hybrid:

```bash
python scripts/build_business_task_ontology_hybrid.py \
  --database-id omnichannel_retail \
  --inventory-dir offline_artifacts/omnichannel_retail/01_database_inventory \
  --object-ontology-dir offline_artifacts/omnichannel_retail/02_object_ontology \
  --output-dir offline_artifacts/omnichannel_retail/03_business_task_ontology \
  --use-llm
```

Build method contracts hybrid:

```bash
python scripts/build_method_contracts_hybrid.py \
  --database-id omnichannel_retail \
  --inventory-dir offline_artifacts/omnichannel_retail/01_database_inventory \
  --object-ontology-dir offline_artifacts/omnichannel_retail/02_object_ontology \
  --task-ontology-dir offline_artifacts/omnichannel_retail/03_business_task_ontology \
  --output-dir offline_artifacts/omnichannel_retail/04_method_contracts \
  --use-llm
```

Build semantic policies:

```bash
python scripts/build_semantic_policies.py \
  --database-id omnichannel_retail \
  --method-contract-dir offline_artifacts/omnichannel_retail/04_method_contracts \
  --task-ontology-dir offline_artifacts/omnichannel_retail/03_business_task_ontology \
  --output-dir offline_artifacts/omnichannel_retail/05_semantic_policies
```

Build retrieval indexes:

```bash
python scripts/build_retrieval_indexes.py \
  --database-id omnichannel_retail \
  --object-ontology-dir offline_artifacts/omnichannel_retail/02_object_ontology \
  --task-ontology-dir offline_artifacts/omnichannel_retail/03_business_task_ontology \
  --method-contract-dir offline_artifacts/omnichannel_retail/04_method_contracts \
  --semantic-policy-dir offline_artifacts/omnichannel_retail/05_semantic_policies \
  --output-dir offline_artifacts/omnichannel_retail/06_retrieval_indexes
```

Build benchmark cases:

```bash
python scripts/build_benchmark_cases.py \
  --database-id omnichannel_retail \
  --inventory-dir offline_artifacts/omnichannel_retail/01_database_inventory \
  --task-ontology-dir offline_artifacts/omnichannel_retail/03_business_task_ontology \
  --method-contract-dir offline_artifacts/omnichannel_retail/04_method_contracts \
  --semantic-policy-dir offline_artifacts/omnichannel_retail/05_semantic_policies \
  --output-dir offline_artifacts/omnichannel_retail/07_benchmark_cases
```

Build offline readiness report:

```bash
python scripts/build_offline_readiness_report.py \
  --database-id omnichannel_retail \
  --offline-root offline_artifacts/omnichannel_retail \
  --output-dir offline_artifacts/omnichannel_retail/08_audit_reports
```

Luồng offline mục tiêu:

```text
00_sources
-> 01_database_inventory
-> 02_object_ontology
-> 03_business_task_ontology
-> 04_method_contracts
-> 05_semantic_policies
-> 06_retrieval_indexes
-> 07_benchmark_cases
-> 08_audit_reports
```

## GitHub Pages

Landing page nằm ở:

```text
landing/index.html
```

Sau khi push lên GitHub, có thể bật GitHub Pages từ folder `/landing` hoặc chuyển nội dung này sang `/docs` tùy cấu hình repo.

## Roadmap

1. Chuẩn hóa semantic policies.
2. Tạo ontology fixed candidate cho `vietnamese_admin_units`.
3. Re-run audit v01.1 để kiểm tra readiness.
4. Thiết kế ontology cho `omnichannel_retail`.
5. Chạy contract audit trên benchmark bán lẻ.
6. Xây runtime v02: structured intent -> ontology planner -> guarded SQL template.
7. Đánh giá với execution accuracy + semantic contract metrics.
