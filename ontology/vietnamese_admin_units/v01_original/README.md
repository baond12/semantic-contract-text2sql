# Vietnamese Admin Units Object Ontology v01

This folder contains machine-readable artifacts for the manual object-oriented ontology design of the `vietnamese_admin_units` database.

Runtime direction:

```text
user question
-> intent parser
-> method selector
-> parameter extractor
-> ontology validator
-> SQL template renderer
-> SQL executor
-> answer formatter
```

Important design decisions:

- `CommuneLevelUnit` maps to the physical table `wards`.
- `Province` maps to the physical table `provinces`.
- `AdministrativeRegion` is currently not connected to `Province` because the database has no region-province relation.
- Combined user requests should be handled by composing atomic methods, not by creating many combined methods.
- The LLM should select methods and parameters only. SQL should be rendered from controlled templates.
