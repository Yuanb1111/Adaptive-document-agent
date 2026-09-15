from adaptive_document_agent.models import AnalysisResult, Observation, SourceEvidence
from adaptive_document_agent.validation import CalculationValidator, EvidenceValidator, ExtractionValidator


def test_conflicting_observations_are_flagged() -> None:
    common = dict(metric_original="Revenue", raw_value="100", period="2025", confidence=0.9)
    report = ExtractionValidator().validate([Observation(id="a", value=100, **common), Observation(id="b", value=120, **common)])
    assert not report.valid
    assert report.issues[0].code == "conflicting_values"


def test_parenthesized_and_positive_source_presentations_are_not_fatal_conflicts() -> None:
    evidence_a = [SourceEvidence(page=1, text="(100)", table_id="statement", extraction_method="digital_table", confidence=0.9)]
    evidence_b = [SourceEvidence(page=2, text="100", table_id="analysis", extraction_method="digital_table", confidence=0.8)]
    common = dict(metric_original="Expense", period="FY2025", confidence=0.9, unit="currency", currency="CNY")
    report = ExtractionValidator().validate(
        [
            Observation(id="negative", value=-100, raw_value="(100)", evidence=evidence_a, **common),
            Observation(id="positive", value=100, raw_value="100", evidence=evidence_b, **common),
        ]
    )
    assert report.valid
    assert [issue.code for issue in report.issues] == ["presentation_sign_variance"]


def test_calculated_result_requires_evidence() -> None:
    result = AnalysisResult(task_id="task", title="Growth", result=10, confidence=0.9)
    assert not EvidenceValidator().validate([result]).valid
    result.evidence = [SourceEvidence(page=1, text="100", extraction_method="digital_table", confidence=0.9)]
    assert EvidenceValidator().validate([result]).valid


def test_failed_calculation_is_error() -> None:
    result = AnalysisResult(task_id="task", title="Growth", result=None, warnings=["missing input"])
    assert not CalculationValidator().validate([result]).valid
