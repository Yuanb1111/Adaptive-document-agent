"""Narrative checks reach synthesis and omissions remain concretely disclosed."""
import json

from adaptive_document_agent.agent.executive_brief import ExecutiveBriefWriter
from adaptive_document_agent.agent.brief_source_checks import source_check_context, uncited_source_checks
from adaptive_document_agent.models.coverage import SourceCheck, SourceCoverage
from adaptive_document_agent.services.presentation_closing import render_closing
from tests.test_executive_brief import gateway, payload, result_for
from tests.test_presentation_brief import blank_deck
from adaptive_document_agent.models import PresentationSlide


def sample():
    constraint = 'Customers may cancel purchases without a long-term commitment.'
    result = result_for(['Revenue was USD 12 million.'] * 11 + [constraint])
    result.profile.source_coverage = SourceCoverage(checks=[SourceCheck(
        section_id='contracts', pages=[12], reason='Check cancellation conditions',
        decision_impact='Changes certainty of future demand', status='checked_found',
        finding=constraint, evidence_quotes={12: [constraint]})])
    return result, constraint


def test_narrative_without_numeric_observations_is_available_despite_other_selected_pages():
    result, constraint = sample()
    g, client = gateway([{'pages': [1]}, payload(constraint, 12, 'Constraints')])
    result.executive_brief = ExecutiveBriefWriter(g).generate(result)
    assert constraint in client.calls[0][1]['content'] and constraint in client.calls[1][1]['content']
    assert not uncited_source_checks(result, result.executive_brief)
    assert not any(i.code == 'source_check_not_referenced' for i in result.validation_warnings)
    assert len(client.calls) == 2 and not result.observations


def test_uncited_found_check_names_question_impact_and_source_in_warning_and_closing():
    result, _ = sample()
    g, _ = gateway([{'pages': [1]}, payload('Revenue was USD 12 million.')])
    result.executive_brief = ExecutiveBriefWriter(g).generate(result)
    warning = next(i for i in result.validation_warnings if i.code == 'source_check_not_referenced')
    assert 'cancellation' in warning.message and 'certainty of future demand' in warning.message
    slides = render_closing(blank_deck(), result, PresentationSlide(id='closing', slide_type='risks', title='Conclusions'))
    text = ' '.join(shape.text for slide in slides for shape in slide.shapes if shape.has_text_frame)
    assert 'Check cancellation conditions' in text and 'Changes certainty of future demand' in text


def test_forged_or_wrong_page_check_never_becomes_source_evidence():
    result, _ = sample()
    result.profile.source_coverage.checks[0].evidence_quotes = {1: ['Invented constraint']}
    records, passages = source_check_context(result)
    assert not passages and not records[0]['evidence'] and not records[0]['context_complete']


def test_synthetic_join_cannot_authorize_quote_missing_from_original_page():
    from adaptive_document_agent.models.executive_brief import ExecutiveBrief
    from adaptive_document_agent.services.executive_brief import validate_executive_brief
    result = result_for(['The estimate is conditional. Material qualifications apply. Demand remains uncertain.'])
    forged = 'The estimate is conditional. Demand remains uncertain.'
    brief = ExecutiveBrief.model_validate(payload(forged))
    assert validate_executive_brief(brief, result, excerpts={1: forged})


def test_many_topic_anchors_cannot_discard_model_selected_narrative_page():
    from adaptive_document_agent.models import PresentationPlan
    constraint = 'Delivery depends on a signed customer approval.'
    texts = [f'Measure {n} was disclosed.' for n in range(1, 12)] + [constraint]
    result = result_for(texts)
    result.presentation_plan = PresentationPlan(title='Review', slides=[
        PresentationSlide(id=f'topic-{n}', slide_type='analysis', title=f'Topic {n}', source_pages=[n])
        for n in range(1, 11)])
    brief = dict(title='Findings', items=[payload(texts[0], 1)['items'][0],
                                       payload(texts[1], 2)['items'][0],
                                       payload(constraint, 12)['items'][0]])
    g, client = gateway([{'pages': [12]}, brief])
    assert ExecutiveBriefWriter(g).generate(result).items[-1].evidence[0].page == 12
    assert constraint in client.calls[1][1]['content'] and len(client.calls) == 2
