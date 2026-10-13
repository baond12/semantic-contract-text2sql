from semantic_contract_text2sql.audit import summarize_audit


def test_summarize_audit_marks_not_ready_when_high_findings_exist():
    findings = [
        {
            "severity": "HIGH",
            "category": "projection_mismatch",
        }
    ]
    tests = [
        {
            "test_status": "PASS",
        }
    ]

    summary = summarize_audit(findings, tests)

    assert summary["finding_count"] == 1
    assert summary["test_count"] == 1
    assert summary["ontology_readiness_status"] == "NOT_READY"

