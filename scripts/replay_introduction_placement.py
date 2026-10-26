"""Replay saved introduction review placement and stop at fresh semantic correction.

Usage: python scripts/replay_introduction_placement.py path/to/analysis.json
Private input stays in place; no provider call or invented correction is made.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adaptive_document_agent.agent.introduction_audience import select_introduction_audience
from adaptive_document_agent.models.summary import SummaryReview


class FreshResolutionRequired(RuntimeError):
    pass


class RecordedIntroduction:
    def __init__(self, record):
        self.record = record
        self.calls = []
        self.resolution_payload = None

    def generate_structured(self, messages, schema, **kwargs):
        self.calls.append(schema.__name__)
        if schema.__name__ == 'IntroductionAudienceSelection':
            decisions = deepcopy(self.record['decisions'])
            # Reconstruct the author wire before Python copied canonical source
            # passages. Feeding canonical quotes back as authored quotes would
            # create new diagnostic proposals and change the recorded digest.
            for decision in decisions:
                for meaning in decision['required_meanings']:
                    meaning['source_quote'] = meaning.pop('proposed_source_quote', '')
            return schema.model_validate(dict(decisions=decisions))
        if schema.__name__ == 'IntroductionAudienceReview':
            assert self.calls.count(schema.__name__) == 1, 'No synthetic re-review is allowed.'
            return schema.model_validate(self.record['raw_review'])
        if schema.__name__ == 'IntroductionMeaningResolution':
            self.resolution_payload = json.loads(messages[-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
            raise FreshResolutionRequired('Fresh model correction and independent review remain required.')
        raise AssertionError('Unexpected operation: ' + schema.__name__)


def replay(path):
    raw = json.loads(Path(path).read_text(encoding='utf-8'))
    audit = json.loads(next(w['message'] for w in reversed(raw['validation_warnings'])
                           if w['code'] == 'company_introduction_summary_audit'))
    records = [p['introduction_audience_review'] for p in audit['plan_audits']
               if 'introduction_audience_review' in p]
    rows = []
    for index, record in enumerate(records):
        if not any('include/omit decision' in e for e in record.get('binding_errors', [])):
            continue
        reading = SummaryReview.model_validate(audit)
        reading.plan_audits = []
        original_parts = deepcopy(reading.parts)
        gateway = RecordedIntroduction(record)
        result = SimpleNamespace(profile=SimpleNamespace(document_purpose=raw['profile']['document_purpose']))
        try:
            select_introduction_audience(gateway, result, reading)
        except FreshResolutionRequired:
            review = next(a['introduction_audience_review'] for a in reading.plan_audits
                          if 'introduction_audience_review' in a)
            assert review['raw_review'] == record['raw_review']
            assert review['decisions'] == record['decisions']
            assert review['selection_digest'] == record['selection_digest']
            assert not review['review']['accepted'] and not reading.audience_selection
            before, after = record['raw_review']['findings'], review['review']['findings']
            assert len(before) == len(after) == len(gateway.resolution_payload['findings'])
            assert gateway.resolution_payload['findings'] == [
                dict(finding_id=f'finding-{i}', **finding) for i, finding in enumerate(after)]
            for first, bound in zip(before, after):
                assert all(first[k] == bound[k] for k in
                    ('part_id', 'meaning_id', 'current_meaning', 'issue_type', 'reason'))
            assert reading.parts == original_parts
            rows.append(dict(record=index, status='reached_fresh_mixed_resolution',
                operations=gateway.calls, retained_findings=len(after),
                placement_changes=len(review['finding_scope_binding']['findings']),
                repair_scope=review['review']['repair_scope'], binding_errors=review['binding_errors'],
                decisions_unchanged=True, source_unchanged=True, semantic_approval=False))
        else:
            raise AssertionError('A recorded rejection must not become selection acceptance.')
    if not rows:
        raise ValueError('No recorded include/omit binding failure found.')
    return dict(recorded_pipeline_version=raw['pipeline_version'], reviews=rows,
        model_calls=0, end_to_end_verified=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path)
    print(json.dumps(replay(parser.parse_args().path), indent=2))
