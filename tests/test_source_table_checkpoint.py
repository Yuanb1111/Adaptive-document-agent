"""A previously unbound table can go straight to independent review on retry."""
import json

import pytest

from adaptive_document_agent.agent.source_integration_quotes import bind_source_quotes
from adaptive_document_agent.agent.source_integration_review import review_supplementary_sources
from adaptive_document_agent.agent.source_table_cells import phrase_cell_options
from adaptive_document_agent.models import ValidationIssue
from adaptive_document_agent.models.executive_brief import BriefComparisonTable, BriefQuote
from tests.test_source_integration_bindings_v206 import case


def checkpoint(mutation):
    result, submitted = case()
    sentence = 'Refunds are available, only with written notice.'
    page = result.document.pages[11]
    page.text += '\n' + sentence
    options = {o['text']: o['ref'] for o in phrase_cell_options(12, page.text)}
    condition, limit = (options[text] for text in ('Refunds are available,', 'only with written notice.'))
    start = page.text.index(sentence)
    span = f'@phrase[12:{start}-{start + len(sentence)}]'
    item = submitted.additions[0]
    item.evidence.append(BriefQuote(page=12, text=sentence))
    item.comparison_table = BriefComparisonTable(headers=['Condition', 'Scope'], rows=[[condition, limit]])
    pages = {12: page.text}
    retained = bind_source_quotes(submitted, pages)
    writer = {f'item_{i}': addition.model_dump(mode='json') for i, addition in enumerate(submitted.additions, 3)}
    # The old menu admitted single clauses only. The current schema admits the complete sentence.
    writer['item_3']['comparison_table']['rows'] = [[span, limit]]
    del writer['item_3']['quantity_representations']  # An omitted optional default is equivalent.
    if mutation == 'copy':
        writer['item_3']['text'] = 'A different conclusion.'
    if mutation == 'evidence':
        writer['item_3']['evidence'].pop()
    if mutation == 'sibling':
        writer['item_4']['label'] = 'Edited accepted sibling'
    if mutation == 'missing':
        del writer['item_4']
    if mutation == 'foreign_page':
        writer['item_3']['comparison_table']['rows'][0][0] = span.replace('[12:', '[1:')
    raw = json.dumps(writer)
    loc = ['item_3', 'comparison_table', 'rows', 0, 0]
    verdicts = [dict(section_id=d.section_id, accepted=i == 1, reason='Prior independent review.')
                for i, d in enumerate(submitted.decisions)]
    entry = dict(draft=retained.model_dump(mode='json'), submitted_draft=submitted.model_dump(mode='json'),
        review=dict(verdicts=verdicts), edited_addition_indexes=[3, 4],
        targeted_format_failure=dict(raw_response=raw, schema_errors=[
            dict(type='missing' if mutation == 'other_error' else 'literal_error', loc=loc)]),
        copy_output_attempts=[dict(status='invalid_format', raw_response=raw,
            usage=dict(finish_reason='length' if mutation == 'incomplete' else 'stop'))])
    attempts = [entry]
    if mutation == 'previous_rejection':
        alternate = retained.model_copy(deep=True)
        alternate.additions[0].comparison_table.rows[0][0] = sentence
        attempts.insert(0, dict(draft=alternate.model_dump(mode='json'), review=dict(verdicts=verdicts)))
    result.failed_stage = 'source_integration'
    result.validation_warnings.append(ValidationIssue(code='source_integration_unresolved', stage='report',
        message=json.dumps(dict(attempts=attempts))))
    return result, submitted, sentence


@pytest.mark.parametrize('mutation', [None, 'copy', 'evidence', 'sibling', 'missing', 'foreign_page',
                                      'other_error', 'incomplete', 'previous_rejection'])
def test_retry_reviews_complete_matching_writer_table_or_calls_the_scoped_writer(mutation):
    result, submitted, sentence = checkpoint(mutation)
    previous = result.model_copy(deep=True)
    calls = []

    class Gateway:
        def generate_structured(self, messages, schema, **kwargs):
            calls.append(schema.__name__)
            if schema.__name__ == 'ReopenedSourceAdditions':
                assert set(schema.model_fields) == {'item_3'}
                return schema(item_3=submitted.additions[0])
            assert schema.__name__ == 'SourceIntegrationReview'
            return schema(verdicts=[dict(section_id=d.section_id, accepted=True, reason='Fresh review.')
                                    for d in submitted.decisions])

    brief = review_supplementary_sources(Gateway(), result, result.executive_brief, previous=previous)
    assert calls == ([] if mutation is None else ['ReopenedSourceAdditions']) + ['SourceIntegrationReview']
    assert brief.items[:3] == previous.executive_brief.items
    assert brief.items[4] == submitted.additions[1]
    assert (brief.items[3].comparison_table.rows[0][0] == sentence) is (mutation is None)


def test_fresh_rejection_of_recovered_table_requires_a_new_writer():
    result, submitted, _ = checkpoint(None)
    previous = result.model_copy(deep=True)
    calls = []

    class Gateway:
        def generate_structured(self, messages, schema, **kwargs):
            calls.append(schema.__name__)
            if schema.__name__ == 'ReopenedSourceAdditions':
                return schema(item_3=submitted.additions[0])
            assert schema.__name__ == 'SourceIntegrationReview'
            return schema(verdicts=[dict(section_id=d.section_id, accepted=i == 1,
                reason='The source qualification is missing.' if i == 0 else 'Source coverage verified.')
                for i, d in enumerate(submitted.decisions)])

    brief = review_supplementary_sources(Gateway(), result, result.executive_brief, previous=previous)
    assert calls[:2] == ['SourceIntegrationReview', 'ReopenedSourceAdditions']
    assert brief == previous.executive_brief
