# Semantic Contract Audit

## Mục tiêu

Audit framework kiểm tra ontology artifacts và SQL templates trước khi phát triển runtime v02.

Không đồng nhất:

```text
test PASS = ontology đúng
```

Nhiều test PASS vì framework phát hiện đúng lỗi đã biết.

## Phase 1A - Ontology Consistency

Kiểm tra tham chiếu:

- class -> parent class,
- property -> class,
- relation -> class/property/inverse relation,
- method -> class/relation/template,
- template -> method.

## Phase 1B - Method Template Contract

Kiểm tra:

- parameter có được preserve không,
- optional parameter có variant không,
- projection có đúng outputProperty không,
- filter có bị drop không,
- ranking có đủ order/limit policy không.

## Phase 1C - Runtime Contract Guard

Nếu method call chứa semantic parameter mà template không đáp ứng, runtime phải:

```json
{
  "status": "blocked",
  "error_code": "SEMANTIC_CONTRACT_VIOLATION",
  "sql_executed": false
}
```

Không được execute SQL im lặng.

## Phase 1D - Contract-driven Tests

Test các lỗi:

- projection mismatch,
- filter preservation,
- modeling gap,
- zero-count risk,
- unsupported relation,
- method composition.

## Phase 1E - Audit Framework Hardening

Bản v01.1 bổ sung:

- negative mutation tests,
- parameter type/range validation,
- root-cause grouping,
- T04/T05/T06 chặt hơn.

