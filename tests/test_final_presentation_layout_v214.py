"""Final native display, including localized copy, decides reporting readiness."""
from copy import deepcopy
from concurrent.futures import CancelledError
import json
import pytest

from adaptive_document_agent.agent.final_presentation_layout import check_final_presentation_layout
from adaptive_document_agent.agent import presentation_budget_refinement as budget
from adaptive_document_agent.services.llm.exceptions import PrivacyViolationError
from tests.test_physical_budget_refinement_v130 import source, measurement


@pytest.mark.parametrize('count,passed', [(18, True), (21, False)])
def test_final_physical_budget_can_reject_previously_complete_result(monkeypatch, count, passed):
    result, _, _, _ = source()
    raw = deepcopy((result.document, result.observations, result.analysis_results))
    result.pipeline_state = 'complete'
    # The final projection is allowed to differ from the earlier measured plan.
    result.presentation_slide_counts = {'total': 18, 'body': 18, 'data_index': 0}
    monkeypatch.setattr(budget, 'measure', lambda current: measurement(current, count, 8))
    assert check_final_presentation_layout(result) == passed
    audit = json.loads(result.validation_warnings[-1].message)
    assert audit['phase'] == 'after_localization'
    assert audit['physical_counts']['body'] == count
    if not passed:
        assert result.pipeline_state == 'partial' and result.retry_from == 'reporting'
        assert result.failed_stage == 'final_presentation_layout'
        assert 'user maximum is 20' in result.failure_details['message']
    assert (result.document, result.observations, result.analysis_results) == raw


def test_final_gate_does_not_hide_composition_failure_as_completed(monkeypatch):
    result, _, _, _ = source()
    def fail(current):
        raise ValueError('Native introduction cannot preserve complete copy')
    monkeypatch.setattr(budget, 'measure', fail)
    assert not check_final_presentation_layout(result)
    assert result.failure_details['message'] == 'Native introduction cannot preserve complete copy'
    assert result.retry_from == 'reporting'


def test_five_logical_intro_pages_expanding_to_six_fail_even_under_total_budget(monkeypatch):
    from adaptive_document_agent.agent.compact_summary import generate_compact_summary
    from adaptive_document_agent.models import PresentationPlan
    from adaptive_document_agent.models.presentation import CompanyProfile
    from adaptive_document_agent.services.presentation_brief import BriefItem, render_brief
    from adaptive_document_agent.services.summary_export import bind_summary_pages
    from tests.test_compact_summary_v111 import fixture, Reviewer
    from tests.test_presentation_brief import blank_deck
    result, review, _ = fixture(5)
    draft = dict(pages=[dict(title=f'Scheduling team {chr(65+i)}', items=[dict(
        label='Service prerequisites', text=part.facts[0].text, fact_ids=[f'f{i}'])])
        for i, part in enumerate(review.parts)])
    company = generate_compact_summary(Reviewer(draft), result, review, CompanyProfile(summary_review=review))
    review.status = 'complete'
    result.presentation_plan = PresentationPlan(title='Source deck', company=company)
    before = deepcopy(company.summary_pages)
    deck = blank_deck()
    for index, page in enumerate(company.summary_pages):
        text = page.items[0].text
        split = text.index(' ', len(text)//2) if index == 0 else len(text)
        pieces = [piece for piece in (text[:split], text[split:]) if piece]
        rendered = [render_brief(deck, page.title, [BriefItem(page.items[0].label, piece, [1])])
                    for piece in pieces]
        bind_summary_pages(rendered, page)
    assert len(deck.slides) == 6 and len(company.summary_pages) == 5
    monkeypatch.setattr(budget, 'measure', lambda current: (deck, dict(total=6, introduction=6)))
    assert not check_final_presentation_layout(result)
    assert 'exceeds its 5-page limit' in result.failure_details['message']
    audit = json.loads(result.validation_warnings[-1].message)
    assert audit['introduction_pages'][0]['slide_numbers'] == [1, 2]
    assert company.summary_pages == before and result.retry_from == 'reporting'


@pytest.mark.parametrize('error', [CancelledError(), PrivacyViolationError('Local only')])
def test_final_gate_propagates_cancellation_and_privacy(monkeypatch, error):
    result, _, _, _ = source()
    def fail(current):
        raise error
    monkeypatch.setattr(budget, 'measure', fail)
    with pytest.raises(type(error)):
        check_final_presentation_layout(result)
    assert not any(w.code == 'final_presentation_layout' for w in result.validation_warnings)
