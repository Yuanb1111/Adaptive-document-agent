"""Offline diagnostic replay of a rejected brief; never certifies an export.

Usage: python scripts/replay_brief_review.py path/to/analysis_data.json
The private input remains read-only. No gateway or network is used.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adaptive_document_agent.agent.brief_claim_direction import BriefClaimDirectionReview, direction_errors
from adaptive_document_agent.agent.brief_meaning_evidence import review_evidence_errors
from adaptive_document_agent.agent.brief_meaning_review import BriefMeaningReview
from adaptive_document_agent.models import PipelineResult
from adaptive_document_agent.models.executive_brief import ExecutiveBrief


def replay(path):
    raw = json.loads(Path(path).read_text(encoding='utf-8'))
    def records(code):
        return [json.loads(w['message']) for w in raw['validation_warnings'] if w['code'] == code]
    repair = records('executive_brief_repair_audit')[-1]
    sources = records('executive_brief_meaning_audit')
    last = sources[-1]
    items = [dict(repair['returned_patch'][f'item_{i}'])
             for i in range(len(repair['original']['items']))]
    for key, changes in repair['post_source_meaning_correction']['proposal'].items():
        items[int(key.removeprefix('item_'))].update(changes)
    brief = ExecutiveBrief(items=items)
    result = PipelineResult.model_validate(raw)
    failures = review_evidence_errors(BriefMeaningReview.model_validate(last['response']), brief=brief,
        pending=[dict(index=int(i), source_audit_scope=scope)
                 for i, scope in last['source_audit_scopes'].items()],
        catalogs={int(i): catalog for i, catalog in last['source_catalogs'].items()}, result=result)
    directions = []
    for record in records('executive_brief_direction_audit'):
        response = BriefClaimDirectionReview.model_validate(record['attempts'][-1]['response'])
        for candidate in reversed(sources):
            by_index = {row['index']: row for row in candidate['response']['items']}
            if all(row.index in by_index and [c.claim for c in row.comparisons] ==
                   [c['claim'] for c in by_index[row.index]['comparisons']] for row in response.items):
                break
        else:
            raise ValueError('Direction audit has no exact matching source comparison ledger')
        verdicts = BriefMeaningReview.model_validate(dict(items=[by_index[r.index] for r in response.items]))
        try:
            errors = direction_errors(response, requested=record['audience'], verdicts=verdicts.items)
            directions.append(dict(reconciliation_required=False, failed_items=sorted(errors)))
        except ValueError:
            directions.append(dict(reconciliation_required=True))
    return dict(pipeline_version=raw['pipeline_version'],
                previous_source_failed_items=sorted(last['errors']), source_failed_items=sorted(failures),
                direction_audits=directions, semantic_approval=False, export_verified=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('analysis_json')
    print(json.dumps(replay(parser.parse_args().analysis_json), indent=2))
