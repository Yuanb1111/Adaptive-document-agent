"""Author references are exact copy bindings, never semantic approval."""
from copy import deepcopy

import pytest

from adaptive_document_agent.agent.compact_summary import (
    CompactSummaryDraft, expand_compact, generate_compact_summary,
)
from adaptive_document_agent.agent.introduction_audience import select_introduction_audience
from adaptive_document_agent.agent.summary_authored_coverage import authored_coverage_errors, meaning_inventory
from adaptive_document_agent.agent.summary_content_repair import (
    SummarySynthesisRevision, apply_content_revision,
)
from adaptive_document_agent.agent.summary_draft_duplicates import deduplicate_draft
from adaptive_document_agent.agent.summary_layout_repair import paginate_draft
from adaptive_document_agent.models.presentation import CompanyProfile
from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, MockLLMClient
from tests.introduction_review_helpers import review_response
from tests.test_compact_summary_v111 import Reviewer, fixture


def authored_fixture():
    result, review, _ = fixture(2)
    source = {'parts': [dict(id=part.id, required_meanings=[
        dict(meaning=part.source_text.split(' and ')[0], source_quote=part.source_text),
        dict(meaning='Staff training is required before service delivery.', source_quote=part.source_text),
    ]) for part in review.parts]}
    catalog = {f'f{i}': (part, 0, part.facts[0]) for i, part in enumerate(review.parts)}
    draft = CompactSummaryDraft(pages=[dict(title='Scheduling prerequisites', items=[dict(
        label='Delivery scope', text=part.source_text.strip(), fact_ids=[f'f{i}'],
        meaning_refs=[dict(part_id=part.id, meaning_index=index, summary_quote=part.source_text.strip())
                      for index in range(2)]) for i, part in enumerate(review.parts)])])
    return result, review, source, catalog, draft


def test_full_inventory_uses_each_exact_source_owned_zero_based_index_once():
    _, _, source, catalog, draft = authored_fixture()
    before = deepcopy(source)
    assert [(r['part_id'], r['meaning_index']) for r in meaning_inventory(source)] == [
        ('part-0', 0), ('part-0', 1), ('part-1', 0), ('part-1', 1)]
    assert all(set(row) == {'part_id', 'meaning_index', 'meaning'} for row in meaning_inventory(source))
    assert all(value['source_quote'] for part in source['parts'] for value in part['required_meanings'])
    audit = {}
    assert authored_coverage_errors(draft, source, catalog, audit) == []
    checked = audit['authored_meaning_coverage']
    assert checked['expected_meaning_count'] == 4 and checked['structurally_complete'] is True
    assert checked['semantic_approval'] is False and checked['missing'] == []
    assert len(checked['references']) == 4 and source == before


@pytest.mark.parametrize('mutation,expected', [
    ('missing', 'missing required meaning'), ('unknown_part', 'unknown required meaning'),
    ('unknown_index', 'unknown required meaning'), ('wrong_owner', 'exact owning source binding'),
    ('other_item_quote', 'not visible in its exact paragraph'),
    ('stale_quote', 'not visible in its exact paragraph'),
    ('blank_quote', 'not visible in its exact paragraph'),
    ('exact_duplicate', 'repeats an exact paragraph reference'),
])
def test_missing_unknown_wrong_owner_and_nonliteral_current_quotes_fail_closed(mutation, expected):
    _, _, source, catalog, draft = authored_fixture()
    item = draft.pages[0].items[0]
    if mutation == 'missing':
        item.meaning_refs.pop(0)
    elif mutation == 'unknown_part':
        item.meaning_refs[0].part_id = 'unknown'
    elif mutation == 'unknown_index':
        item.meaning_refs[0].meaning_index = 17
    elif mutation == 'wrong_owner':
        item.fact_ids = ['f1']
    elif mutation == 'other_item_quote':
        item.meaning_refs[0].summary_quote = draft.pages[0].items[1].text
    elif mutation == 'stale_quote':
        item.meaning_refs[0].summary_quote = 'A previous wording that is no longer visible.'
    elif mutation == 'blank_quote':
        item.meaning_refs[0].summary_quote = '   '
    elif mutation == 'exact_duplicate':
        item.meaning_refs.append(item.meaning_refs[0].model_copy(deep=True))
    audit = {}
    errors = authored_coverage_errors(draft, source, catalog, audit)
    assert any(expected in error for error in errors)
    assert audit['authored_meaning_coverage']['structurally_complete'] is False
    assert audit['authored_meaning_coverage']['semantic_approval'] is False


def test_all_indices_may_span_paragraphs_but_each_ref_needs_its_own_visible_binding():
    _, _, source, catalog, draft = authored_fixture()
    first = draft.pages[0].items[0]
    first.text = 'Team AA supports scheduling.'
    first.meaning_refs = [first.meaning_refs[0].model_copy(update={'summary_quote': first.text})]
    second = first.model_copy(deep=True)
    second.text = 'Staff training is required before service delivery.'
    second.meaning_refs = [first.meaning_refs[0].model_copy(update={
        'meaning_index': 1, 'summary_quote': second.text})]
    draft.pages[0].items.insert(1, second)
    audit = {}
    assert authored_coverage_errors(draft, source, catalog, audit) == []
    # Moving a quote to its neighbour does not authorize a paragraph-local ref.
    first.meaning_refs.append(second.meaning_refs[0])
    assert any('not visible in its exact paragraph' in error
               for error in authored_coverage_errors(draft, source, catalog, {}))


def test_duplicate_copy_merges_every_distinct_reference_without_mutating_original():
    _, _, source, catalog, draft = authored_fixture()
    text = 'Teams AA and AB support scheduling; staff training precedes service delivery.'
    left = draft.pages[0].items[0]
    left.text, left.fact_ids = text, ['f0', 'f1']
    left.meaning_refs = [ref.model_copy(update={'summary_quote': text}) for ref in left.meaning_refs]
    right = draft.pages[0].items[1]
    right.text, right.fact_ids = text, ['f1', 'f0']
    right.meaning_refs = [ref.model_copy(update={'summary_quote': text}) for ref in right.meaning_refs]
    original = draft.model_copy(deep=True)
    audit = {}
    reconciled = deduplicate_draft(draft, audit)
    assert len(reconciled.pages[0].items) == 1 and draft == original
    refs = reconciled.pages[0].items[0].meaning_refs
    assert {(r.part_id, r.meaning_index) for r in refs} == {
        ('part-0', 0), ('part-0', 1), ('part-1', 0), ('part-1', 1)}
    assert len(refs) == 4 and authored_coverage_errors(reconciled, source, catalog, {}) == []
    assert audit['identical_copy_reconciliation'][0]['original_item'] == right.model_dump(mode='json')


def test_source_or_copy_changes_are_never_merged_as_identical_duplicates():
    _, _, _, _, draft = authored_fixture()
    first = draft.pages[0].items[0]
    first.text = draft.pages[0].items[1].text
    assert len(deduplicate_draft(draft, {}).pages[0].items) == 2  # Different exact facts.
    first.fact_ids = ['f1']
    first.text += ' Additional source qualification.'
    assert len(deduplicate_draft(draft, {}).pages[0].items) == 2  # Different visible copy.


def test_revision_must_update_references_to_the_actual_new_paragraph():
    _, _, source, catalog, draft = authored_fixture()
    replacement = draft.pages[0].items[0].model_copy(deep=True)
    replacement.text = 'Team AA provides scheduling, with staff training before delivery.'
    revision = SummarySynthesisRevision(replacements=[dict(page_index=0, item_index=0,
                                                          replacement=replacement)])
    revised = apply_content_revision(draft, revision, CompactSummaryDraft)
    assert any('not visible in its exact paragraph' in error
               for error in authored_coverage_errors(revised, source, catalog, {}))
    assert authored_coverage_errors(draft, source, catalog, {}) == []
    for ref in revised.pages[0].items[0].meaning_refs:
        ref.summary_quote = replacement.text
    assert authored_coverage_errors(revised, source, catalog, {}) == []


def test_layout_rewrite_is_rechecked_after_pagination_not_against_previous_copy():
    _, review, source, catalog, draft = authored_fixture()
    first, second = draft.pages[0].items
    draft.pages[0].items = [first]
    draft.pages.append(draft.pages[0].model_copy(update={'title': 'Other scheduling scope', 'items': [second]}))
    review.max_intro_slides = 1
    revised = draft.model_copy(deep=True)
    revised.pages = [revised.pages[0]]
    item = revised.pages[0].items[0]
    item.text = 'Teams AA and AB provide scheduling; staff preparation is required before service delivery.'
    item.fact_ids = ['f0', 'f1']
    item.meaning_refs.extend(ref.model_copy(deep=True) for ref in second.meaning_refs)
    client = MockLLMClient([revised.model_dump(mode='json')])
    gateway = LLMGateway(client, LLMSettings())
    audit = {}
    current, pages = paginate_draft(gateway, draft, catalog, review, [], audit,
                                    expand_compact, CompactSummaryDraft)
    assert len(client.calls) == 1 and len(pages) == 1
    assert audit['layout_attempts'][0]['status'] == 'overflow'
    assert any('not visible in its exact paragraph' in error
               for error in authored_coverage_errors(current, source, catalog, {}))


def test_complete_author_self_report_cannot_override_independent_rejection():
    result, review, draft = fixture(2)
    class SelectionClient:
        def generate_structured(self, messages, schema, **kwargs):
            if schema.__name__ == 'IntroductionAudienceSelection':
                return schema(decisions=[dict(part_id=part.id, include=True, reason='Distinct delivery scope.',
                    required_meanings=[dict(meaning='Staff training is required before service delivery.')])
                    for part in review.parts])
            return review_response(schema, messages, accepted=True, reason='Both source scopes are material.')
    select_introduction_audience(SelectionClient(), result, review)
    client = Reviewer(draft, reject='part-1')
    with pytest.raises(ValueError, match='Source meaning is absent|rejected draft'):
        generate_compact_summary(client, result, review, CompanyProfile(summary_review=review))
    checks = [row['authored_meaning_coverage'] for row in review.plan_audits
              if 'authored_meaning_coverage' in row]
    assert checks and all(check['structurally_complete'] and check['semantic_approval'] is False for check in checks)
    rejected = [row['compact_semantic_review'] for row in review.plan_audits
                if 'compact_semantic_review' in row]
    assert rejected and any(part['accepted'] is False for row in rejected for part in row['parts'])
    assert review.status == 'incomplete'
