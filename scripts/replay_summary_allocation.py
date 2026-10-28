"""Replay recorded introduction copy with a MOCK final complete-item transfer.

Usage: python -m scripts.replay_summary_allocation analysis.json
Blocks network, checks literal preservation and native pagination. A mock choice
is not semantic acceptance, and this script does not export/approve a report.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
from unittest.mock import patch


def replay(path):
    with (patch('socket.socket.connect', side_effect=AssertionError('Offline replay')),
          patch('socket.socket.connect_ex', side_effect=AssertionError('Offline replay'))):
        return _replay(path)


def _replay(path):
    from adaptive_document_agent.agent.compact_summary import SummarySynthesisDraft, compact_input, expand_compact
    from adaptive_document_agent.agent.summary_layout_allocation import allocation_choices
    from adaptive_document_agent.agent.summary_layout_repair import paginate_draft
    from adaptive_document_agent.agent.summary_layout_feedback import compression_binding_errors, selected_meaning_source
    from adaptive_document_agent.agent.summary_authored_coverage import authored_coverage_errors
    from adaptive_document_agent.agent.summary_writer_copy import address_only_copy
    from adaptive_document_agent.models.summary import SummaryReview
    from adaptive_document_agent.services.compact_summary import compact_layout_errors

    raw = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    review = SummaryReview.model_validate_json(next(w['message'] for w in reversed(raw['validation_warnings'])
        if w['code'] == 'company_introduction_summary_audit'))
    _, catalog = compact_input(review)
    attempts = next(p['layout_attempts'] for p in reversed(review.plan_audits) if len(p.get('layout_attempts', [])) >= 2)
    initial = SummarySynthesisDraft.model_validate(attempts[0]['draft'])
    rewritten = SummarySynthesisDraft.model_validate(attempts[1]['draft'])
    options = allocation_choices(rewritten, catalog, review, expand_compact)
    if not options:
        raise ValueError('No complete-item transfer meets this recorded physical budget')

    class MockSelection:
        def __init__(self):
            self.operations = []

        def generate_structured(self, messages, schema, **kwargs):
            self.operations.append(schema.__name__)
            if self.operations == ['SummaryLayoutPages']:
                return schema.model_validate(dict(pages=address_only_copy(rewritten.model_dump(mode='json')['pages'])))
            assert self.operations == ['SummaryLayoutPages', 'SummaryLayoutAllocation']
            return schema.model_validate(dict(choice=next(iter(options))))

    mock, audit = MockSelection(), {}
    final, pages = paginate_draft(mock, initial, catalog, review, [], audit, expand_compact, SummarySynthesisDraft)
    assert Counter(i.model_dump_json() for p in final.pages for i in p.items) == Counter(
        i.model_dump_json() for p in rewritten.pages for i in p.items)
    errors = compression_binding_errors(final, initial, catalog)
    errors += authored_coverage_errors(final, selected_meaning_source(review), catalog, {})
    errors += compact_layout_errors(pages)
    assert not errors, errors

    from pptx import Presentation
    from adaptive_document_agent.models.summary_display import SummaryDisplay
    from adaptive_document_agent.services.pptx_export import _resolve_template_path
    from adaptive_document_agent.services.presentation_brief import BriefItem, render_profile
    deck, rendered = Presentation(_resolve_template_path()), []
    for page in pages:
        rendered.extend(render_profile(deck, page.title, [BriefItem(i.label, i.text, i.source_pages,
            display=i.display or SummaryDisplay()) for i in page.items]))
    assert len(rendered) == len(pages) <= review.max_intro_slides
    visible = ''.join(s.text for slide in rendered for s in slide.shapes if s.name == 'brief:body')
    assert visible == ''.join(i.text for page in pages for i in page.items)
    return dict(pipeline_version=raw['pipeline_version'], budget=review.max_intro_slides,
        candidate_transfers=options, operations=mock.operations,
        physical_page_history=[a['layout_feedback']['score']['body_slides'] for a in audit['layout_attempts']],
        native_generated_pages=len(rendered), all_paragraphs_and_bindings_unchanged=True,
        validation_errors=errors, selection_response='mock_first_measured_transfer',
        semantic_approval=False, export_verified=False, real_model_calls=0)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('analysis_json')
    print(json.dumps(replay(parser.parse_args().analysis_json), indent=2))
