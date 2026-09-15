from adaptive_document_agent.models import DocumentProfile, Observation, SourceEvidence
from adaptive_document_agent.validation import CoverageValidator, assess_coverage


def test_dynamic_coverage_uses_profile_topics_without_fixed_financial_fields() -> None:
    evidence = [SourceEvidence(page=12, text="120", table_id="source", extraction_method="digital_table", confidence=0.9)]
    profile = DocumentProfile(metrics=["Customer retention", "Regional mix"])
    observations = [
        Observation(
            id="retention",
            metric_original="Customer retention rate",
            value=92,
            raw_value="92%",
            unit="percent",
            period="FY2025",
            evidence=evidence,
            confidence=0.9,
        )
    ]
    coverage = assess_coverage(profile, observations)
    assert [(item.topic, item.status) for item in coverage] == [("Customer retention", "Covered"), ("Regional mix", "Missing")]
    report = CoverageValidator(profile).validate(observations)
    assert [issue.code for issue in report.issues] == ["coverage_gap"]
