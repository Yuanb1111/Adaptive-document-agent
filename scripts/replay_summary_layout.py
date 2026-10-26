"""Replay introduction pagination offline; measured choices are NOT semantic approval.

Usage: python scripts/replay_summary_layout.py path/to/analysis_data.json
Reads the private diagnostic without copying or changing it. No model calls.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adaptive_document_agent.agent.compact_summary import SummarySynthesisDraft, compact_input, expand_compact
from adaptive_document_agent.agent.summary_authored_coverage import authored_coverage_errors
from adaptive_document_agent.agent.summary_layout_choices import layout_choices
from adaptive_document_agent.agent.summary_layout_feedback import compression_binding_errors, selected_meaning_source
from adaptive_document_agent.agent.summary_theme_layout import pack_theme_pages
from adaptive_document_agent.models.summary import SummaryReview
from adaptive_document_agent.services.compact_summary import compact_layout_errors


def replay(path):
    raw = json.loads(Path(path).read_text(encoding='utf-8'))
    audit = json.loads(next(row['message'] for row in reversed(raw['validation_warnings'])
                           if row['code'] == 'company_introduction_summary_audit'))
    review = SummaryReview.model_validate(audit)
    _, catalog = compact_input(review)
    result = []
    for plan in review.plan_audits:
        for attempt in plan.get('layout_attempts', []):
            if 'draft' not in attempt:
                continue
            draft = SummarySynthesisDraft.model_validate(attempt['draft'])
            before = pack_theme_pages(expand_compact(draft, catalog, review))
            choices = layout_choices(draft, catalog, review, expand_compact)
            proposed = draft.model_copy(deep=True)
            for row in choices.values():
                proposed.pages[row['index']] = row['page']
            after = pack_theme_pages(expand_compact(proposed, catalog, review))
            errors = compression_binding_errors(proposed, draft, catalog)
            errors += authored_coverage_errors(proposed, selected_meaning_source(review), catalog, {})
            errors += compact_layout_errors(after)
            result.append(dict(attempt=attempt['attempt'], original_pages=len(before),
                candidate_pages=len(after), choices={key: dict(before=row['original_pages'],
                    after=row['inline_pages']) for key, row in choices.items()},
                validation_errors=errors))
    return dict(pipeline_version=raw['pipeline_version'], budget=review.max_intro_slides,
                attempts=result, semantic_approval=False, export_verified=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('analysis_json')
    print(json.dumps(replay(parser.parse_args().analysis_json), indent=2))
