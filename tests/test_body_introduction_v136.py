"""Body-only caps retain complete reading and independently select visible meanings."""
from tests.introduction_review_helpers import review_response
from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from adaptive_document_agent.agent import summary_presentation
from adaptive_document_agent.agent.compact_summary import generate_compact_summary, SummarySynthesisDraft
from adaptive_document_agent.models import PresentationPlan, ValidationIssue
from adaptive_document_agent.models.presentation import CompanyProfile
from adaptive_document_agent.services.company_summary import require_verified_introduction
from adaptive_document_agent.services.export import export_pptx_with_report
from adaptive_document_agent.services.export_diagnostics import export_diagnostics
from adaptive_document_agent.services.presentation_requirements import apply_presentation_budget, fixed_presentation_budget
from tests.test_compact_summary_v111 import fixture, Reviewer


class AudienceClient(Reviewer):
    def __init__(self, draft, reading, *, accepted=True):
        super().__init__(draft)
        self.reading, self.accepted = reading, accepted

    def generate_structured(self, messages, schema, **kwargs):
        if schema.__name__ == 'IntroductionAudienceSelection':
            self.calls.append(schema.__name__)
            return schema(decisions=[dict(part_id=p.id, include=p.id == 'part-0',
                reason='Core service and prerequisite.' if p.id == 'part-0' else
                       'Same service and prerequisite already represented by the core source.',
                required_meanings=[dict(meaning=p.reading_note)] if p.id == 'part-0' else [])
                for p in self.reading.parts])
        if schema.__name__ == 'IntroductionAudienceReview':
            self.calls.append(schema.__name__)
            return review_response(schema, messages, accepted=self.accepted, reason='Reviewed actual service scope and training prerequisite.')
        return super().generate_structured(messages, schema, **kwargs)


@pytest.mark.parametrize('scope', ['body', 'all', 'introduction_body'])
def test_bounded_introduction_selects_meanings_after_complete_reading(monkeypatch, scope):
    result, reading, _ = fixture(3)
    result.profile.report_requirements = apply_presentation_budget(None, '', fixed_presentation_budget())
    if scope == 'all':
        for requirement in result.profile.report_requirements.items:
            requirement.slide_scope = 'all'
    elif scope == 'introduction_body':
        result.profile.report_requirements.items = [r for r in result.profile.report_requirements.items
                                                    if r.slide_section == 'introduction']
    original = deepcopy(reading.parts)
    def read(gateway, result, review, **kwargs):
        review.source_blocks = deepcopy(reading.source_blocks)
        review.parts = deepcopy(reading.parts)
    monkeypatch.setattr(summary_presentation, 'read_summary', read)
    draft = dict(pages=[dict(title='Scheduling service', items=[dict(label='Scope and prerequisite',
        text=reading.parts[0].source_text.strip(), fact_ids=['f0'])])])
    client = AudienceClient(draft, reading)
    company = summary_presentation.generate_summary_presentation(client, result, [1], object,
                                                                 scope_ranges=reading.scope_ranges)
    review = company.summary_review
    assert review.parts == original and review.status == 'complete'
    assert review.audience_part_ids == ['part-0']
    assert len(review.audience_selection['decisions']) == 3
    assert review.audience_selection['independent_review']['accepted']
    assert len(company.summary_pages) == 1 and company.summary_pages[0].placement == 'body'
    assert company.summary_pages[0].items[0].source_pages == [1]
    assert client.calls == ['IntroductionAudienceSelection', 'IntroductionAudienceReview',
                            'SummarySynthesisDraft', 'SummaryCoverageReview']
    audit = json.loads(result.validation_warnings[-1].message)
    assert len(audit['parts']) == 3 and len(audit['audience_selection']['decisions']) == 3


def test_body_cap_cannot_skip_audience_rejection(monkeypatch):
    result, reading, draft = fixture(3)
    result.profile.report_requirements = apply_presentation_budget(None, '', fixed_presentation_budget())
    def read(gateway, result, review, **kwargs):
        review.source_blocks, review.parts = reading.source_blocks, reading.parts
    monkeypatch.setattr(summary_presentation, 'read_summary', read)
    client = AudienceClient(draft, reading, accepted=False)
    with pytest.raises(ValueError, match='training prerequisite'):
        summary_presentation.generate_summary_presentation(client, result, [1], object)
    assert client.calls == ['IntroductionAudienceSelection', 'IntroductionAudienceReview'] * 2
    assert json.loads(result.validation_warnings[-1].message)['status'] == 'incomplete'


def test_fixed_body_introduction_cannot_put_detail_in_an_appendix():
    result, reading, draft = fixture(3)
    result.profile.report_requirements = apply_presentation_budget(None, '', fixed_presentation_budget())
    draft['pages'].append(dict(title='Supporting context', placement='appendix',
                              items=deepcopy(draft['pages'][0]['items'])))
    client = Reviewer(draft)
    with pytest.raises(ValueError, match='Supporting introduction appendices'):
        generate_compact_summary(client, result, reading, CompanyProfile(summary_review=reading),
                                 draft_schema=SummarySynthesisDraft)
    assert not any('Review' in name for name in client.calls)


def test_late_introduction_failure_reports_original_cause_and_keeps_export_blocked():
    result, _, _ = fixture(1)
    result.pipeline_state, result.retry_from = 'partial', 'reporting'
    result.presentation_plan = PresentationPlan(title='Retained analysis', planning_origin='topic_compilation',
        company=CompanyProfile(one_line_description='A source-verified company introduction is unavailable for this run.'))
    reason = 'Complete introduction theme unavailable: source-part: missing a source qualification.'
    result.validation_warnings.append(ValidationIssue(code='company_introduction_unavailable',
        message=reason, stage='presentation'))
    original = result.model_dump()
    with pytest.raises(ValueError, match='missing a source qualification') as failure:
        require_verified_introduction(result)
    renderer = Mock(side_effect=AssertionError('Never render an incomplete introduction'))
    with pytest.raises(ValueError, match='source-verified opening'):
        export_pptx_with_report(result, renderer=renderer, force=True)
    renderer.assert_not_called()
    report = export_diagnostics(result, failure.value)
    assert report['export_error']['stage'] == 'introduction'
    assert report['critical_errors'][0]['code'] == 'INTRODUCTION_VERIFICATION_FAILED'
    assert report['critical_errors'][0]['message'] == reason
    assert report['is_export_blocked'] and result.model_dump() == original


def test_ui_explains_late_failure_and_preserves_downloadable_diagnostics(monkeypatch):
    from adaptive_document_agent.ui import deliverables
    from tests.test_analysis_export_diagnostics import DownloadUI
    result, _, _ = fixture(1)
    result.pipeline_state, result.retry_from = 'partial', 'reporting'
    result.validation_warnings.append(ValidationIssue(code='company_introduction_unavailable',
        message='A material source qualification is missing.', stage='presentation'))
    ui, progress = DownloadUI(), Mock()
    ui.error = Mock()
    monkeypatch.setattr('adaptive_document_agent.services.presentation_editorial.review_presentation', lambda *a: [])
    deliverables.render(ui, result, b'untrusted PDF bytes', progress)
    messages = ' '.join(call.args[0] for call in ui.error.call_args_list)
    assert 'incomplete' in messages and 'Retry analysis (reuse successful cache)' in messages
    diagnostic = json.loads(ui.downloads['analysis_data.json'])['pptx_export_diagnostics']
    assert diagnostic['export_error']['stage'] == 'introduction'
    assert diagnostic['critical_errors'][0]['message'] == 'A material source qualification is missing.'
    assert 'analysis_presentation.pptx' not in ui.downloads
    progress.fail.assert_called_once()
