"""Reject cosmetic source repairs and preserve separate numeric/sign failures."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.compact_summary import generate_compact_summary
from adaptive_document_agent.agent.summary_repair_progress import source_failure_keys
from adaptive_document_agent.models.presentation import CompanyProfile
from tests.test_compact_summary_v111 import fixture, Reviewer


def test_joined_failures_retain_paragraph_identity_and_accounting_sign():
    errors = ["Results: unsupported numeric claims ['7', '2'].; "
              "Results: amount changes a source accounting sign: claimed usd 7; source usd -7.; "
              "Reconciliation: unsupported numeric claims ['2']."]
    keys = source_failure_keys(errors)
    assert 'Results: unsupported numeric claim 2' in keys
    assert 'Reconciliation: unsupported numeric claim 2' in keys
    assert any('accounting sign' in key for key in keys)
    assert len(keys) == 4


@pytest.mark.parametrize('persistent', [False, True])
def test_cosmetic_repair_of_spelled_count_gets_one_targeted_retry(persistent):
    result, review, valid = fixture(1)
    invalid = deepcopy(valid)
    invalid['pages'][0]['items'][0]['text'] += ' There are two service periods.'
    class Client(Reviewer):
        repairs = 0
        def generate_structured(self, messages, schema, **kwargs):
            if schema.__name__ == 'SummarySynthesisRevision':
                self.calls.append(schema.__name__)
                self.repairs += 1
                item = deepcopy(invalid['pages'][0]['items'][0])
                item['text'] = item['text'].replace('There are', 'The service covers')
                if self.repairs == 2:
                    feedback = json.loads(messages[-2]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
                    assert feedback['remaining_errors']
                    assert "['2']" in str(feedback['remaining_errors'])
                    assert 'spelled-out numbers' in messages[0]['content']
                    if not persistent:
                        item = deepcopy(valid['pages'][0]['items'][0])
                return schema(replacements=[dict(item_id='g0_i0', replacement=item)])
            return super().generate_structured(messages, schema, **kwargs)
    client = Client(invalid)
    company = CompanyProfile(summary_review=review)
    if persistent:
        with pytest.raises(ValueError, match='did not reduce'):
            generate_compact_summary(client, result, review, company)
        assert not company.summary_pages
        assert 'CompactSummaryReview' not in client.calls
    else:
        generate_compact_summary(client, result, review, company)
        assert company.summary_pages
        assert client.calls[-1] == 'CompactSummaryReview'
    assert client.repairs == 2
    assert review.plan_audits[-1]['content_revision_attempts'][0]['status'] == 'rejected'
