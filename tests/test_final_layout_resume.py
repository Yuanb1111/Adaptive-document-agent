"""A final display retry reuses only independently source-reviewed content."""
import os
from pathlib import Path

import pytest

from adaptive_document_agent.agent.final_layout_resume import retry_final_layout
from adaptive_document_agent.models import PipelineResult


def recorded():
    path = os.getenv('ADA_FINAL_LAYOUT_DIAGNOSTIC')
    if not path:
        pytest.skip('Set ADA_FINAL_LAYOUT_DIAGNOSTIC to a private final-display checkpoint.')
    return PipelineResult.model_validate_json(Path(path).read_bytes())


@pytest.mark.parametrize('change', ['source', 'value', 'claim', 'calculation', 'focus', 'stage'])
def test_changed_inputs_cannot_reuse_completed_source_reviews(change):
    result = recorded()
    if change == 'source':
        target = next(s for s in result.presentation_plan.slides if s.slide_type == 'analysis')
        page = next(p for p in result.document.pages if p.page_number in target.source_pages)
        page.text += 'Changed literal source.'
    elif change == 'value':
        target = next(s for s in result.presentation_plan.slides if s.slide_type == 'analysis')
        next(o for o in result.observations if o.id in target.observation_ids).raw_value = '999999'
    elif change == 'claim':
        result.executive_brief.items[0].text += 'An additional unreviewed finding.'
    elif change == 'calculation':
        result.analysis_results[0].confidence = .123
    elif change == 'focus':
        assert retry_final_layout(result, None, requested_focus='Different report priorities') is None
        return
    else:
        result.failed_stage = 'executive_brief'
    before = result.model_dump_json()
    assert retry_final_layout(result, None) is None
    assert result.model_dump_json() == before


def test_recorded_display_retry_retains_reviewed_content_and_rechecks_missing_copy():
    import json
    result = recorded()
    before = result.model_dump_json()
    class Gateway:
        usage = []
        def __init__(self):
            self.calls = []
        def generate_structured(self, messages, schema, **kwargs):
            self.calls.append(schema.__name__)
            rows = json.loads(messages[-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
            if schema.__name__ == 'CopyTranslations':
                return schema(items=[dict(id=row['id'], text=row['original']) for row in rows])
            assert schema.__name__ == 'TranslationReview'
            return schema(items=[dict(id=row['id'], accepted=True,
                                     reason='Synthetic independent language protocol check.') for row in rows])
    gateway = Gateway()
    final = retry_final_layout(result, gateway)
    assert final is not None and final.pipeline_state == 'complete'
    assert final.failed_stage is None and final.retry_from is None and not final.failure_details
    assert gateway.calls == ['CopyTranslations', 'TranslationReview']
    assert result.model_dump_json() == before
    assert final.model_dump(include={'document', 'observations', 'analysis_results', 'executive_brief'}) == (
        result.model_dump(include={'document', 'observations', 'analysis_results', 'executive_brief'}))
