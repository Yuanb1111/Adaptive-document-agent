"""Final audit qualifications supersede an earlier parallel briefing snapshot."""
from adaptive_document_agent.agent.report_audit_scope import defer_brief_for_audit
from tests.test_report_audit_scope_v174 import fixture


class Prepared:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True

    def result(self, current):
        raise AssertionError('The old unaudited snapshot must never be accepted')


def test_final_plan_new_audit_scope_cancels_prepared_brief_without_adopting_it():
    result, _ = fixture()
    result.presentation_plan.themes[0].caveats = []
    prepared = Prepared()
    assert not defer_brief_for_audit(result, prepared)
    assert not prepared.closed
    result.presentation_plan.themes[0].caveats = ['6M2025 audit status is unknown.']
    assert defer_brief_for_audit(result, prepared)
    assert prepared.closed
    assert result.executive_brief is None


def test_audit_scope_defers_serial_brief_without_a_parallel_worker():
    result, _ = fixture()
    assert defer_brief_for_audit(result)
