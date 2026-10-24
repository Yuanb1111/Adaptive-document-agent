"""Replay a saved failed meaning-resolution response locally without model calls."""
import argparse
from copy import deepcopy
import json
from pathlib import Path

from adaptive_document_agent.agent.introduction_audience import IntroductionAudienceSelection
from adaptive_document_agent.agent.introduction_audience_review import IntroductionAudienceReview
from adaptive_document_agent.agent.introduction_meaning_resolution import (
    IntroductionMeaningResolution, resolve_meaning_findings)
from adaptive_document_agent.models.summary import SummaryReview


def replay(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    audit = json.loads(next(w['message'] for w in data['validation_warnings']
                           if w['code'] == 'company_introduction_summary_audit'))
    reading = SummaryReview.model_validate(audit)
    saved = next(row['introduction_meaning_resolution'] for row in reversed(reading.plan_audits)
                 if 'introduction_meaning_resolution' in row)
    selection = IntroductionAudienceSelection(decisions=saved['decisions_before'])
    response = IntroductionMeaningResolution.model_validate(saved['response'])
    verdict = IntroductionAudienceReview(accepted=False, reason='Replay the saved exact findings.',
        repair_scope='selection', findings=[{k: v for k, v in f.items() if k != 'finding_id'}
                                           for f in saved['findings']])
    source = dict(parts=[p.model_dump(exclude={'facts'}) for p in reading.parts if p.role == 'content'])
    before = deepcopy((selection, source, saved, response))

    class SavedResponseGateway:
        calls = 0

        def generate_structured(self, messages, schema, **kwargs):
            self.calls += 1
            assert schema is IntroductionMeaningResolution and self.calls == 1
            return response.model_copy(deep=True)

    gateway = SavedResponseGateway()
    draft, ledger = resolve_meaning_findings(gateway, source, selection,
        selection.model_dump(mode='json')['decisions'], verdict, reading)
    record = reading.plan_audits[-1]['introduction_meaning_resolution']
    assert (selection, source, saved, response) == before
    assert record['response'] == saved['response']
    assert ledger['semantic_approval'] is False and not reading.audience_selection
    for inclusion in response.inclusions:
        decision = next(d for d in draft.decisions if d.part_id == inclusion.part_id)
        assert decision.include and decision.reason == inclusion.reason
        assert decision.required_meanings == inclusion.required_meanings
    return dict(saved_version=data['pipeline_version'], saved_failure=data['failure_details'],
        replay_status=record['status'], model_requests=0,
        coalesced_inclusion_addition_part_ids=record['coalesced_inclusion_addition_part_ids'],
        coalesced_unchanged_meaning_ids=record['coalesced_unchanged_meaning_ids'],
        append_only_edits=record.get('append_only_edits', []),
        findings=len(saved['findings']), edits=len(response.edits),
        explicit_inclusions=len(response.inclusions), raw_response_preserved=True,
        semantic_approval=False,
        remaining='Fresh independent semantic review and subsequent reporting/export are still required.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('analysis_json')
    args = parser.parse_args()
    print(json.dumps(replay(args.analysis_json), ensure_ascii=True, indent=2))
