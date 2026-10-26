"""Replay a recorded unchanged correction; stop before unrecorded model adjudication."""
import argparse
from copy import deepcopy
import json
from pathlib import Path

from adaptive_document_agent.agent.introduction_audience import IntroductionAudienceSelection
from adaptive_document_agent.agent.introduction_audience_review import IntroductionAudienceReview
from adaptive_document_agent.agent.introduction_meaning_resolution import (
    IntroductionMeaningResolution, resolve_meaning_findings)
from adaptive_document_agent.models.summary import SummaryReview


class FreshAdjudicationRequired(RuntimeError):
    pass


def replay(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    audit = json.loads(next(w['message'] for w in data['validation_warnings']
        if w['code'] == 'company_introduction_summary_audit'))
    reading = SummaryReview.model_validate(audit)
    saved = next(row['introduction_meaning_resolution'] for row in reversed(reading.plan_audits)
                 if 'introduction_meaning_resolution' in row)
    selection = IntroductionAudienceSelection(decisions=saved['decisions_before'])
    response = IntroductionMeaningResolution.model_validate(saved['protocol_attempts'][0]['response'])
    verdict = IntroductionAudienceReview(accepted=False, reason='Replay saved findings.',
        findings=[{k:v for k,v in finding.items() if k != 'finding_id'} for finding in saved['findings']])
    source = dict(parts=[p.model_dump(exclude={'facts'}) for p in reading.parts if p.role == 'content'])
    before = deepcopy((selection, source, response))

    class Gateway:
        calls = []
        original_messages = None
        context = None

        def generate_structured(self, messages, schema, **kwargs):
            self.calls.append(schema.__name__)
            if schema is IntroductionMeaningResolution:
                assert len(self.calls) == 1
                self.original_messages = deepcopy(messages)
                return response.model_copy(deep=True)
            assert schema.__name__ == 'UnchangedMeaningDecision'
            assert messages[:2] == self.original_messages
            self.context = json.loads(messages[2]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
            assert self.context['current_meaning'] == self.context['proposed_meaning']
            raise FreshAdjudicationRequired()

    gateway = Gateway()
    try:
        resolve_meaning_findings(gateway, source, selection,
            selection.model_dump(mode='json')['decisions'], verdict, reading)
    except FreshAdjudicationRequired:
        assert (selection, source, response) == before
        record = reading.plan_audits[-1]['introduction_meaning_resolution']
        assert record['protocol_attempts'][0]['response'] == response.model_dump(mode='json')
        assert len(record['findings']) == len(saved['findings'])
        assert not reading.audience_selection
        return dict(status='reached_fresh_unchanged_adjudication', operations=gateway.calls,
            retained_findings=len(saved['findings']), exact_unchanged_copy=True,
            source_and_selection_unchanged=True, model_calls=0, semantic_approval=False,
            end_to_end_verified=False)
    raise AssertionError('A recorded rejection cannot become automatic acceptance.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('analysis_json')
    print(json.dumps(replay(parser.parse_args().analysis_json), indent=2))
