"""Optional offline replay; private diagnostics never become repository fixtures."""
import json
import os
from pathlib import Path

import pytest

from adaptive_document_agent.agent.introduction_audience import select_introduction_audience
from adaptive_document_agent.models import PipelineResult
from adaptive_document_agent.models.summary import SummaryReview
from adaptive_document_agent.services.llm import MockLLMClient
from adaptive_document_agent.services.llm.base import LLMResponse
from adaptive_document_agent.services.llm.exceptions import LLMResponseError
from tests.test_reporting_checkpoint_v142 import _gateway, _payloads


@pytest.mark.parametrize('patch_only', [False, True])
def test_recorded_inventory_reaches_mandatory_review_without_rewriting_protected_parts(patch_only):
    path = os.environ.get('ADA_INVENTORY_DIAGNOSTIC')
    if not path:
        pytest.skip('Set ADA_INVENTORY_DIAGNOSTIC to a private recorded inventory failure')
    result = PipelineResult.model_validate_json(Path(path).read_text(encoding='utf-8'))
    audit = json.loads(next(w.message for w in result.validation_warnings
                           if w.code == 'company_introduction_summary_audit'))
    original = next(a['invalid_selection'] for a in audit['plan_audits'] if 'invalid_selection' in a)
    correction = next(a['introduction_audience_inventory_correction'] for a in audit['plan_audits']
                      if 'introduction_audience_inventory_correction' in a)
    reading = SummaryReview.model_validate(audit)
    reading.plan_audits = []
    original_parts = reading.model_dump()['parts']

    class RecordedClient(MockLLMClient):
        def __init__(self):
            super().__init__()

        def generate_text(self, messages, **kwargs):
            name = json.loads(messages[0]['content'].split('Return only JSON matching this schema: ', 1)[1])['title']
            self.calls.append(name)
            if name == 'IntroductionAudienceSelection':
                return LLMResponse(text=json.dumps(original))
            if name == 'IntroductionAudienceInventoryCorrection':
                payload = _payloads(messages)[-1]
                self.protected = payload['protected_decisions']
                self.repaired_ids = payload['repair_part_ids']
                decisions = correction['decisions']
                if patch_only:
                    decisions = [d for d in decisions if d['part_id'] in self.repaired_ids]
                return LLMResponse(text=json.dumps(dict(decisions=decisions)))
            assert name == 'IntroductionAudienceReview'
            self.review_payload = _payloads(messages)[-1]
            # The diagnostic stopped before independent review. Do not fabricate
            # acceptance or treat a repaired transport inventory as a passed deck.
            raise LLMResponseError('Recorded independent review is unavailable')

    client = RecordedClient()
    with pytest.raises(LLMResponseError, match='Recorded independent review is unavailable'):
        select_introduction_audience(_gateway(client), result, reading)
    assert client.calls == ['IntroductionAudienceSelection', 'IntroductionAudienceInventoryCorrection',
                            'IntroductionAudienceReview']
    merged = reading.plan_audits[1]['merged_selection']['decisions']
    actual = {d['part_id']: d for d in merged}
    assert len(actual) == len([p for p in reading.parts if p.role == 'content'])
    assert all(actual[d['part_id']] == d for d in client.protected)
    assert set(client.repaired_ids) == set(actual) - {d['part_id'] for d in client.protected}
    assert client.review_payload['inventory_revision_base'] == original
    assert reading.model_dump()['parts'] == original_parts
    assert reading.audience_part_ids is None and not reading.audience_selection
