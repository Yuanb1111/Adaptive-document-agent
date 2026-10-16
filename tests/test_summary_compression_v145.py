"""Physical compression is bounded and cannot remove mandatory meaning or evidence."""
from copy import deepcopy

import pytest

from adaptive_document_agent.agent.compact_summary import (
    CompactSummaryDraft, SummarySynthesisDraft, compact_input, expand_compact, generate_compact_summary,
)
from adaptive_document_agent.agent.summary_draft_protocol import SummaryDraftProtocolError
from adaptive_document_agent.agent.summary_layout_feedback import (
    compression_progress, layout_feedback,
)
from adaptive_document_agent.agent.summary_layout_repair import paginate_draft
from adaptive_document_agent.models.presentation import CompanyProfile
from tests.test_compact_summary_v111 import fixture, Reviewer
from tests.test_total_file_budget_v130 import choose


def compression_fixture():
    result, review, _ = fixture(3)
    review.max_intro_slides = 1
    choose(result, review, selected=tuple(part.id for part in review.parts))
    _, catalog = compact_input(review)
    original = CompactSummaryDraft(pages=[dict(title='Scheduling prerequisites', items=[dict(
        label='Service scope', text=part.source_text.strip(), fact_ids=[f'f{i}'],
        meaning_refs=[dict(part_id=part.id, meaning_index=0,
                           summary_quote=part.source_text.strip())])])
        for i, part in enumerate(review.parts)])
    packed = original.model_copy(deep=True)
    packed.pages = [packed.pages[0].model_copy(update={
        'items': [page.items[0] for page in packed.pages]})]
    return result, review, catalog, original, packed


class DraftClient:
    def __init__(self, *drafts):
        self.drafts, self.calls = list(drafts), []

    def generate_structured(self, messages, schema, **kwargs):
        self.calls.append(deepcopy(messages))
        return schema.model_validate(self.drafts.pop(0).model_dump(mode='json'))


def paginate(client, draft, catalog, review, audit, **kwargs):
    return paginate_draft(client, draft, catalog, review, [], audit,
                           expand_compact, CompactSummaryDraft, **kwargs)


def test_second_bounded_compression_recovers_after_no_geometry_improvement():
    _, review, catalog, original, packed = compression_fixture()
    client, audit = DraftClient(original, packed), {}
    current, pages = paginate(client, original, catalog, review, audit)
    assert current == packed and len(pages) == 1 and len(client.calls) == 2
    attempts = audit['layout_attempts']
    assert [row['status'] for row in attempts] == ['overflow', 'overflow', 'success']
    assert attempts[1]['compression_progress']['improved'] is False
    assert attempts[2]['compression_progress']['improved'] is True
    assert all(row['layout_feedback']['semantic_approval'] is False for row in attempts)
    assert attempts[1]['compression_round'] == attempts[1]['compression_round_limit'] == 2
    assert 'FINAL bounded' in client.calls[1][-1]['content']
    assert 'did not improve' in client.calls[1][-1]['content']


def test_final_overflow_stops_after_exactly_two_compressions():
    _, review, catalog, original, _ = compression_fixture()
    client, audit = DraftClient(original, original), {}
    with pytest.raises(SummaryDraftProtocolError, match='layout repair exhausted'):
        paginate(client, original, catalog, review, audit)
    assert len(client.calls) == 2 and len(audit['layout_attempts']) == 3
    assert all(row['status'] == 'overflow' for row in audit['layout_attempts'])
    assert not any(row.get('rendered_pages') for row in audit['layout_attempts'])


@pytest.mark.parametrize('mutation', ['missing', 'unknown', 'wrong_owner', 'stale_quote',
                                    'removed_fact', 'changed_identity'])
def test_compression_cannot_use_shorter_geometry_to_bypass_source_bindings(mutation):
    _, review, catalog, original, packed = compression_fixture()
    item = packed.pages[0].items[0]
    if mutation == 'missing': item.meaning_refs.clear()
    elif mutation == 'unknown': item.meaning_refs[0].meaning_index = 7
    elif mutation == 'wrong_owner': item.fact_ids = ['f1']
    elif mutation == 'stale_quote': item.meaning_refs[0].summary_quote = 'Previous draft wording.'
    elif mutation == 'removed_fact': packed.pages[0].items.pop()
    elif mutation == 'changed_identity': packed.stock_code = 'invented'
    client, audit = DraftClient(packed), {}
    with pytest.raises(SummaryDraftProtocolError, match='source preservation'):
        paginate(client, original, catalog, review, audit)
    assert len(client.calls) == 1
    assert [row['status'] for row in audit['layout_attempts']] == ['overflow', 'source_invalid']
    assert 'physical_groups' not in audit['layout_attempts'][1]


def test_initial_missing_reference_remains_in_the_existing_source_repair_phase():
    _, review, catalog, _, packed = compression_fixture()
    packed.pages[0].items[0].meaning_refs.clear()
    client, audit = DraftClient(), {}
    current, pages = paginate(client, packed, catalog, review, audit)
    assert current == packed and len(pages) == 1 and not client.calls
    assert audit['layout_attempts'][0]['status'] == 'success'
    # generate_compact_summary's unchanged post-pagination source validation
    # can now use its targeted SummarySynthesisRevision path.
    from adaptive_document_agent.agent.summary_authored_coverage import authored_coverage_errors
    from adaptive_document_agent.agent.summary_layout_feedback import selected_meaning_source
    assert any('missing required meaning' in error for error in authored_coverage_errors(
        current, selected_meaning_source(review), catalog, {}))


@pytest.mark.parametrize('placement', ['all_appendix', 'supporting_appendix'])
def test_compression_cannot_evade_the_selected_whole_introduction_cap_using_appendices(placement):
    _, review, catalog, original, packed = compression_fixture()
    initial = SummarySynthesisDraft.model_validate(original.model_dump())
    data = packed.model_dump()
    if placement == 'all_appendix':
        data['pages'][0]['placement'] = 'appendix'
    else:
        body, tail = data['pages'][0], deepcopy(data['pages'][0])
        body['placement'], tail['placement'] = 'body', 'appendix'
        body['items'], tail['items'] = body['items'][:1], tail['items'][1:]
        data['pages'] = [body, tail]
    candidate = SummarySynthesisDraft.model_validate(data)
    client, audit = DraftClient(candidate), {}
    with pytest.raises(SummaryDraftProtocolError, match='cannot create supporting appendices'):
        paginate_draft(client, initial, catalog, review, [], audit, expand_compact, SummarySynthesisDraft)
    assert len(client.calls) == 1 and audit['layout_attempts'][-1]['status'] == 'source_invalid'


def test_additive_late_omission_cannot_spend_the_new_compression_budget():
    _, review, catalog, original, _ = compression_fixture()
    client, audit = DraftClient(), {}
    with pytest.raises(SummaryDraftProtocolError, match='Additive omission correction'):
        paginate(client, original, catalog, review, audit, allow_rewrite=False)
    assert not client.calls and len(audit['layout_attempts']) == 1


def test_feedback_retains_every_meaning_and_exposes_exact_geometry_and_ownership():
    _, review, catalog, original, _ = compression_fixture()
    item = original.pages[0].items[0]
    # One visible statement can carry multiple independent source bindings.
    item.fact_ids.append('f1')
    item.meaning_refs.append(original.pages[1].items[0].meaning_refs[0].model_copy(
        update={'summary_quote': item.text}))
    pages = expand_compact(original, catalog, review)
    feedback = layout_feedback(original, pages, review, catalog)
    assert feedback['semantic_approval'] is False
    assert feedback['template']['body_font_pt'] == 16
    assert len(feedback['meaning_assignments']) == 3
    assert feedback['score']['body_slides'] == 3
    paragraph = feedback['groups'][0]['paragraphs'][0]
    assert paragraph['full_width_height_inches'] > 0
    assert paragraph['fact_ids'] == ['f0', 'f1']
    assert len(feedback['shared_literal_quotes']) == 1
    assert len(feedback['shared_literal_quotes'][0]['references']) == 2
    assert feedback['repeated_source_ownership'] == [dict(part_id='part-1', item_ids=['g0_i0', 'g1_i0'])]
    longer = original.model_copy(deep=True)
    longer.pages[0].title = 'Scheduling prerequisites across supported operating sites'
    measured = layout_feedback(longer, expand_compact(longer, catalog, review), review, catalog)
    assert measured['groups'][0]['title_lines'] > feedback['groups'][0]['title_lines']
    assert measured['groups'][0]['body_capacity_inches'] < feedback['groups'][0]['body_capacity_inches']


def test_fewer_words_without_geometry_progress_do_not_count_as_progress_or_acceptance():
    previous = dict(score=dict(body_slides=7, excess_body_slides=2, estimated_body_occupied_inches=14.0))
    shorter = deepcopy(previous)
    shorter['words'] = 20
    progress = compression_progress(previous, shorter)
    assert progress['improved'] is False and progress['semantic_approval'] is False
    shorter['score']['estimated_body_occupied_inches'] = 13.9
    assert compression_progress(previous, shorter)['improved'] is True


def test_successful_compression_still_requires_a_fresh_independent_meaning_verdict():
    result, review, _, original, packed = compression_fixture()

    class Client(Reviewer):
        authors = 0

        def generate_structured(self, messages, schema, **kwargs):
            if issubclass(schema, CompactSummaryDraft):
                self.authors += 1
                self.draft = [original, packed][min(self.authors - 1, 1)].model_dump(mode='json')
            return super().generate_structured(messages, schema, **kwargs)

    client = Client(original.model_dump(mode='json'), reject='part-1')
    with pytest.raises(ValueError, match='Source meaning is absent|rejected draft'):
        generate_compact_summary(client, result, review, CompanyProfile(summary_review=review))
    assert client.authors == 2 and 'SummaryCoverageReview' in client.calls
    first = next(row for row in review.plan_audits if 'compact_attempt' in row)
    assert first['layout_attempts'][-1]['status'] == 'success'
    assert first['fresh_complete_meaning_review'] is True
    assert any(v['accepted'] is False for v in first['compact_semantic_review']['parts'])
    assert review.status == 'incomplete'


def test_native_title_overflow_uses_bounded_layout_repair_without_rewriting_body():
    _, review, catalog, _, packed = compression_fixture()
    initial = packed.model_copy(deep=True)
    initial.pages[0].title = ('WWWW ' * 13).strip()
    client, audit = DraftClient(packed), {}
    current, pages = paginate(client, initial, catalog, review, audit)
    assert current == packed and len(pages) == 1 and len(client.calls) == 1
    first = audit['layout_attempts'][0]
    assert first['status'] == 'overflow' and first['title_errors']
    assert first['layout_feedback']['pagination_complete'] is False
    assert first['layout_feedback']['score']['body_slides'] is None
    assert first['layout_feedback']['score']['invalid_titles'] == 1
    assert first['layout_feedback']['template']['max_native_title_lines'] == 3
    assert 'Repair only the overflowing logical group titles' in client.calls[0][-1]['content']
    assert [item.model_dump() for item in current.pages[0].items] == [
        item.model_dump() for item in initial.pages[0].items]
    final = audit['layout_attempts'][1]
    assert final['status'] == 'success' and final['compression_progress']['improved'] is True
    assert final['layout_feedback']['pagination_complete'] is True


def test_unfixed_native_title_overflow_stops_with_the_same_layout_budget():
    _, review, catalog, _, packed = compression_fixture()
    packed.pages[0].title = ('WWWW ' * 13).strip()
    client, audit = DraftClient(packed, packed), {}
    with pytest.raises(SummaryDraftProtocolError, match='layout repair exhausted.*title'):
        paginate(client, packed, catalog, review, audit)
    assert len(client.calls) == 2 and len(audit['layout_attempts']) == 3
    assert all(row['status'] == 'overflow' and row['title_errors'] for row in audit['layout_attempts'])


def test_native_numbered_paragraph_heading_overflow_repairs_the_label_only():
    _, review, catalog, _, packed = compression_fixture()
    initial = packed.model_copy(deep=True)
    initial.pages[0].items[0].label = 'Service scope\nDelivery condition\nTraining requirement'
    client, audit = DraftClient(packed), {}
    current, pages = paginate(client, initial, catalog, review, audit)
    assert current == packed and len(pages) == 1 and len(client.calls) == 1
    first = audit['layout_attempts'][0]
    assert first['status'] == 'overflow' and first['paragraph_heading_errors']
    assert first['layout_feedback']['pagination_complete'] is False
    assert first['layout_feedback']['score']['invalid_paragraph_headings'] == 1
    assert 'Repair only the overflowing paragraph labels' in client.calls[0][-1]['content']
    assert 'Do not split or shorten body text' in client.calls[0][-1]['content']
    assert [item.text for item in current.pages[0].items] == [item.text for item in initial.pages[0].items]
