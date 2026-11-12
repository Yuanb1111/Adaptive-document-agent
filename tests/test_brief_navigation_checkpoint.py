"""Derived section links must not discard an exact approved briefing."""
import json

import pytest

from adaptive_document_agent.agent.brief_reporting_resume import checked_integration_input
from adaptive_document_agent.agent.brief_review_checkpoint import checkpoint_context_matches
from adaptive_document_agent.agent.source_coverage import link_coverage
from adaptive_document_agent.models.coverage import SourceCoverage, SectionCoverage, SourceCheck
from tests.test_retained_brief_reporting_resume import checkpoint, approve_preintegration_input


def linked_checkpoint():
    saved, _, _ = checkpoint()
    saved.profile.source_coverage = SourceCoverage(sections=[SectionCoverage(id='section', title='Results',
        start_page=234, end_page=234)], checks=[SourceCheck(section_id='section', pages=[234],
        reason='Source qualification', decision_impact='Context', status='checked_found', finding='Reported results')])
    approve_preintegration_input(saved)
    link_coverage(saved.profile.source_coverage, saved.observations, saved.presentation_plan)
    current = saved.model_copy(deep=True)
    current.executive_brief = None
    return saved, current


def test_navigation_linking_preserves_exact_source_approval_without_model_requests():
    saved, current = linked_checkpoint()
    before = current.model_dump()
    record = json.loads(saved.validation_warnings[-1].message)
    assert current.profile.source_coverage.sections[0].observation_ids
    assert checkpoint_context_matches(record, saved.executive_brief, current)
    assert checked_integration_input(saved, current) == saved.executive_brief
    assert current.model_dump() == before


@pytest.mark.parametrize('changed', ['value', 'source', 'focus', 'budget', 'plan', 'finding', 'scope', 'foreign_links'])
def test_navigation_compatibility_cannot_hide_source_or_semantic_changes(changed):
    saved, current = linked_checkpoint()
    if changed == 'value':
        current.observations[0].raw_value = '999999'
    elif changed == 'source':
        current.document.pages[0].text += ' A new limitation.'
    elif changed == 'focus':
        current.profile.analysis_focus = 'Different user priorities'
    elif changed == 'budget':
        current.profile.report_requirements = None
        current.profile.data_quality_notes.append('A different output constraint')
    elif changed == 'plan':
        current.presentation_plan.slides[-1].title += ' Changed'
    elif changed == 'finding':
        current.profile.source_coverage.checks[0].finding += ' Changed qualification'
    elif changed == 'scope':
        current.profile.source_coverage.sections[0].end_page = 235
    else:
        current.profile.source_coverage.sections[0].observation_ids = ['unrelated-id']
    assert checked_integration_input(saved, current) is None
