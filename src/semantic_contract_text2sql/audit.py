from collections import Counter
from typing import Any


def summarize_audit(audit_findings: list[dict[str, Any]], test_results: list[dict[str, Any]]) -> dict[str, Any]:
    severity_counts = Counter(item.get("severity", "UNKNOWN") for item in audit_findings)
    category_counts = Counter(item.get("category", "unknown") for item in audit_findings)
    test_status_counts = Counter(item.get("test_status", "UNKNOWN") for item in test_results)

    ontology_readiness = "READY"
    if severity_counts.get("CRITICAL", 0) > 0 or severity_counts.get("HIGH", 0) > 0:
        ontology_readiness = "NOT_READY"

    return {
        "finding_count": len(audit_findings),
        "finding_count_by_severity": dict(severity_counts),
        "finding_count_by_category": dict(category_counts),
        "test_count": len(test_results),
        "test_count_by_status": dict(test_status_counts),
        "ontology_readiness_status": ontology_readiness,
    }

