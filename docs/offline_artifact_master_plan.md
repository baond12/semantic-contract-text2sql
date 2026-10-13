# Offline Artifact Master Plan

Tài liệu này mô tả cách tổ chức dữ liệu offline cho một database trước khi đưa vào runtime Text2SQL.

Mục tiêu là tách rõ:

```text
database có gì
-> object ontology mô tả database
-> task ontology mô tả user có thể hỏi gì
-> method contract nối task với object
-> semantic policy kiểm soát đúng/sai nghiệp vụ
-> retrieval index giúp online scale
-> benchmark và audit để kiểm chứng
```

## Target Flow

### Offline

```text
database schema/metadata
-> build Object Ontology
-> build Task Ontology
-> build vector/BM25 indexes cho intent/class/property/method/value
```

### Online

```text
user question
-> retrieve candidate intents
-> retrieve candidate objects/properties/values
-> build small context
-> LLM parse Task State
-> validate với 2 ontology
-> map Method Call
-> render SQL
```

## Folder Structure

```text
offline_artifacts/
  <database_id>/
    00_sources/
    01_database_inventory/
    02_object_ontology/
    03_business_task_ontology/
    04_method_contracts/
    05_semantic_policies/
    06_retrieval_indexes/
    07_benchmark_cases/
    08_audit_reports/
    manifest.json
```

## 00_sources

Nguồn dữ liệu gốc, không chỉnh sửa.

Xây từ:

```text
structural_profile.json
enriched_metadata.json
DDL/schema.sql
sample values
business documents nếu có
scenario/testcase templates nếu có
```

## 01_database_inventory

Chuẩn hóa database thành inventory dễ xử lý.

Output kỳ vọng:

```text
tables.json
columns.json
relationships.json
sample_values.json
database_overview.json
```

## 02_object_ontology

Ontology mô tả database theo hướng đối tượng.

Output kỳ vọng:

```text
ontology_classes.json
ontology_properties.json
ontology_relations.json
ontology_methods.json
unsupported_scope.json
sql_templates.json
manifest.json
```

Với `vietnamese_admin_units`, phần này hiện đã có ở:

```text
ontology/vietnamese_admin_units/v01_original/
```

hoặc trên server theo workspace Q4:

```text
/home/baond12/projects/Text2Sql_Q4/2026-10-12/ontology/vietnamese_admin_units_object_ontology_v01/
```

## 03_business_task_ontology

Ontology mô tả user có thể hỏi nhóm nghiệp vụ nào và thao tác gì.

Output kỳ vọng:

```text
business_intents.json
operation_intents.json
task_slots.json
task_values.json
task_scenarios.json
task_examples.json
task_clarification_policy.json
task_unsupported_policy.json
manifest.json
```

Thiết kế nên tách:

```text
Business Intent = hỏi về nghiệp vụ/lĩnh vực nào
Operation Intent = muốn thao tác gì: count, list, rank, lookup...
```

## 04_method_contracts

Nối Task Ontology với Object Ontology.

Output kỳ vọng:

```text
method_contracts.json
intent_method_mappings.json
method_parameters.json
method_sql_template_mappings.json
```

## 05_semantic_policies

Quy tắc đúng/sai về nghiệp vụ.

Output kỳ vọng:

```text
required_semantics.json
forbidden_semantics.json
metric_definitions.json
time_grain_policy.json
join_policy.json
security_policy.json
```

Ví dụ retail:

```text
GMV không cộng shipping_fee
Net Sales phải trừ approved refund
Paid order phải có payment success
```

## 06_retrieval_indexes

Index để online không phải load toàn bộ ontology.

Output kỳ vọng:

```text
bm25_index/
vector_index/
intent_cards.json
class_cards.json
property_cards.json
method_cards.json
value_cards.json
```

## 07_benchmark_cases

Bộ đánh giá.

Output kỳ vọng:

```text
scenario_matrix.xlsx
test_cases.xlsx
gold_sql.sql
expected_results.json
negative_examples.json
scoring_rules.json
```

## 08_audit_reports

Kết quả kiểm tra offline.

Output kỳ vọng:

```text
ontology_consistency_report.json
method_contract_audit.json
semantic_policy_audit.json
coverage_report.json
readiness_summary.json
```

## Readiness Principle

Không nên xem một ontology là sẵn sàng chỉ vì SQL chạy được.

Ontology chỉ nên chuyển sang runtime khi:

```text
object ontology consistent
task ontology coverage đủ
method contract preserve đầy đủ parameter
semantic policies được kiểm tra
unsupported/clarify/refuse được định nghĩa
retrieval context đủ nhỏ để scale
```

