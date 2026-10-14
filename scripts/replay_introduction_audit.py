"""Recheck saved introductory draft/evidence bindings without model requests."""
import argparse
import json
from pathlib import Path

from adaptive_document_agent.agent.compact_summary import CompactSummaryDraft, compact_input, expand_compact
from adaptive_document_agent.models import PipelineResult
from adaptive_document_agent.models.summary import SummaryReview
from adaptive_document_agent.services.compact_summary import compact_item_errors, compact_continuation_errors
from adaptive_document_agent.services.summary_validation import reading_errors


def replay(path):
    result = PipelineResult.model_validate_json(Path(path).read_text(encoding='utf-8'))
    audit = next(json.loads(w.message) for w in result.validation_warnings
                 if w.code == 'company_introduction_summary_audit')
    review = SummaryReview.model_validate(audit)
    themes = next(a['theme_plan']['themes'] for a in reversed(review.plan_audits)
                  if 'theme_plan' in a and not a.get('error'))
    failures = []
    pending = []
    paragraphs = 0
    for index, theme in enumerate(themes):
        drafts = [a['draft'] for a in review.plan_audits if a.get('theme_index') == index and 'draft' in a]
        if not drafts:
            pending.append(index)
            continue
        by_id = {p.id: p for p in review.parts}
        parts = [by_id[pid] for pid in theme['part_ids']]
        probe = review.model_copy(update={'parts': parts, 'decisions': [], 'plan_audits': []})
        _, catalog = compact_input(probe)
        pages = expand_compact(CompactSummaryDraft.model_validate(drafts[-1]), catalog, probe)
        groups = {}
        errors = []
        for page in pages:
            for item in page.items:
                if item.continuation_group:
                    groups.setdefault(item.continuation_group, []).append(item)
                else:
                    paragraphs += 1
                    errors.extend(compact_item_errors(item, probe, result))
        paragraphs += len(groups)
        errors.extend(compact_continuation_errors(groups, probe, result))
        if errors:
            failures.append({'theme': index, 'errors': errors})
    return {'saved_version': result.pipeline_version, 'themes': len(themes), 'paragraphs': paragraphs,
            'source_reading_errors': reading_errors(review, result), 'draft_source_failures': failures,
            'themes_not_yet_authored': pending,
            'semantic_review': 'A corrected failed theme still requires a fresh independent model review.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('analysis_json')
    args = parser.parse_args()
    print(json.dumps(replay(args.analysis_json), ensure_ascii=True, indent=2))
