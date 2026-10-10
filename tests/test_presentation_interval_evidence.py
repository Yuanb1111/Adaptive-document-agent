"""Latest pair facts expose counterpoints without forcing semantic selection."""
from adaptive_document_agent.agent.presentation_topic_selector import series_directory
from adaptive_document_agent.services.presentation_interval_evidence import latest_numeric_intervals
from tests.test_topic_coverage_review import _fixture, _observation


def test_latest_change_does_not_collapse_a_reversal_into_its_endpoint_direction():
    points = [_observation('Capacity', 'FY2021', 150), _observation('Capacity', 'FY2022', 300),
              _observation('Capacity', 'FY2023', 73), _observation('Capacity', 'FY2024', 81)]
    before = [o.model_dump() for o in points]
    assert latest_numeric_intervals(points) == [['FY2023', 'FY2024', '8.0']]
    assert [o.model_dump() for o in points] == before


def test_latest_interval_never_compares_annual_with_interim_flow():
    result, directory, lookup, annual, interim, _ = _fixture()
    assert next(d for d in directory if d['id'] == annual)['latest_numeric_intervals'] == [
        ['FY2022', 'FY2023', '100.0']]
    assert next(d for d in directory if d['id'] == interim)['latest_numeric_intervals'] == [
        ['6M2023', '6M2024', '-20.0']]
    combined = latest_numeric_intervals(lookup[annual] + lookup[interim])
    assert len(combined) == 2
    assert not any(start == 'FY2023' and end == '6M2024' for start, end, _ in combined)


def test_invalid_latest_point_does_not_authorize_a_stale_latest_comparison():
    points = [_observation('Capacity', 'FY2022', 300), _observation('Capacity', 'FY2023', 73),
              _observation('Capacity', 'FY2024', 81)]
    points[-1].validation_status = 'invalid'
    assert latest_numeric_intervals(points) == []
    points[-1].validation_status = 'valid'
    points[-1].value = None
    assert latest_numeric_intervals(points) == []
