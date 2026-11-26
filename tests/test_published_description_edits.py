"""Published source copy can be recovered only against the same slot, proof and prior review."""
import json
from types import SimpleNamespace

import pytest

from adaptive_document_agent.agent.published_description_edits import unresolved_published_comparisons
from adaptive_document_agent.agent.retained_page_revision import (
    PublishedPageEdits, PublishedPageRevisions, _recover_misplaced_edits,
)
from adaptive_document_agent.agent.reported_source_context import QualifiedSourceCopy, qualified_source_statement
from adaptive_document_agent.services.llm.base import LLMResponse
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
from adaptive_document_agent.services.llm.usage import LLMUsage


@pytest.mark.parametrize('problem', [
    None, 'canonical_map', 'wrong_proof', 'wrong_scope', 'unpublished_scope', 'still_oversized', 'arbitrary_prefix',
])
def test_restore_overlong_display_description_only_if_recompilation_is_identical(problem):
    proof = 'The source reports the applicable terms.'
    item = QualifiedSourceCopy(scope='the operating review and supporting material',
                               description='reports the applicable terms.', quote={'page': 8, 'text': proof})
    current = {'item': {'page': {'title': 'Terms', 'message': 'See the terms.',
                                 'source_context': [item.model_dump()]}}}
    published = {'item': {'context-0': qualified_source_statement(item)}}
    fixed = 'the source reports ' + 'supporting terms and conditions, ' * 20 + 'as previously agreed.'
    if problem == 'still_oversized':
        fixed += ' More supporting terms and conditions.'
    text = qualified_source_statement(item.model_copy(update={'description': fixed}))
    assert len(text) > 700
    if problem == 'wrong_scope':
        text = text.replace('the operating review', 'another review', 1)
    if problem == 'arbitrary_prefix':
        text = 'Additional meaning. ' + text
    if problem == 'unpublished_scope':
        published['item']['context-0'] = 'The source also reports the applicable terms.'
    edits = {'item': {'source_context_descriptions': {'context-0': text}}}
    other = {'title': [{'span_id': 'copy-0', 'after': 'Other topic'}]}
    wrapper = {'pages': {}, 'edits': edits}
    if problem == 'canonical_map':
        edits['other'] = other
    else:
        wrapper['other'] = other
    error = LLMStructuredOutputError('Bounded schema validation', response=LLMResponse(
        text=json.dumps(wrapper), usage=LLMUsage(provider='mock', model='mock', finish_reason='stop')))
    def recover():
        return _recover_misplaced_edits(error, {'item', 'other'}, PublishedPageRevisions, current=current,
            published=published, pages={8: SimpleNamespace(text='Missing original proof' if problem == 'wrong_proof' else proof)})
    if problem not in (None, 'canonical_map'):
        with pytest.raises(LLMStructuredOutputError) as failure:
            recover()
        assert failure.value is error
    else:
        result = recover()
        new, = result.edits['item'].source_context_descriptions.values()
        assert new == fixed and qualified_source_statement(item.model_copy(update={'description': new})) == text
        assert result.edits['other'].title[0].after == 'Other topic'


@pytest.mark.parametrize('case', ['omitted', 'named', 'other_owner', 'no_quoted_comparison', 'different_interval'])
def test_check_only_reviewer_quoted_source_owned_comparison(case):
    display = 'For liquidity, the source attributes the decline through 2024-06-30 to slower receipts.'
    reason = 'Name working capital and both dates for “the decline through 2024-06-30.”'
    draft = 'The source attributes the decline from December 31, 2023 to June 30, 2024 to slower receipts.'
    label = 'Working capital'
    if case == 'named':
        draft = draft.replace('the decline from', 'the decline in working capital from')
    elif case == 'other_owner':
        label = 'Other amount'
    elif case == 'different_interval':
        draft = draft.replace('2023', '2022')
    elif case == 'no_quoted_comparison':
        reason = 'Check the cited explanation for working capital.'
    patch = PublishedPageEdits(source_context_descriptions={'context-0': draft})
    packet = {'primary_observations': [{'metric_original': label, 'period': p}
                                      for p in ['2022-12-31', '2023-12-31', '2024-06-30']],
              'published_source_descriptions': {'context-0': display}}
    page = SimpleNamespace(message='Working capital declined from 2023-12-31 to 2024-06-30.')
    errors = unresolved_published_comparisons(patch, page, packet, [reason])
    assert bool(errors) == (case == 'omitted')
