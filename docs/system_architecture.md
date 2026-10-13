# System Architecture

## Pipeline mục tiêu

```text
User Question
      |
      v
Semantic Intent Parser
      |
      v
Structured Query Intent
      |
      v
Ontology-based Planner
      |
      v
Semantic Contract Validator
      |
      v
SQL Template Resolver
      |
      v
SQL Executor
      |
      v
Result Validator
      |
      v
Answer Formatter
```

## Tư tưởng chính

LLM không nên sinh SQL tự do nếu hệ thống đã có ontology method và SQL template.

Vai trò mong muốn của LLM:

```text
question -> structured intent / method call
```

Vai trò của hệ thống:

```text
validate -> render SQL -> execute -> evaluate
```

## Object ontology

Ontology gồm:

- `Class`: đối tượng nghiệp vụ.
- `Property`: thuộc tính.
- `Relation`: quan hệ giữa object.
- `Method`: thao tác được phép.
- `SQL Template`: implementation có kiểm soát.
- `Unsupported Scope`: phạm vi không trả lời.

## Semantic contract

Semantic contract cần bảo toàn:

- projection,
- filter,
- parameter,
- relation,
- aggregation,
- ranking population,
- unsupported/refuse decision.

