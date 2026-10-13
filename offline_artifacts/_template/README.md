# Offline Artifacts Template

Template này dùng để khởi tạo workspace offline cho từng database.

Tạo workspace mới bằng script:

```bash
python scripts/init_offline_artifacts.py \
  --database-id vietnamese_admin_units \
  --output-root offline_artifacts
```

Sau khi tạo, cấu trúc sẽ là:

```text
offline_artifacts/<database_id>/
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

