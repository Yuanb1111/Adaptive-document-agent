"""Flattened assurance headers cannot lend their status to adjacent periods."""
import json

import pytest

from adaptive_document_agent.agent.brief_audit_scope import audit_status_errors, source_audit_scope
from adaptive_document_agent.agent.brief_meaning_review import meaning_validator
from adaptive_document_agent.agent.brief_semantic_repair import correct_new_meaning_errors
from tests.test_brief_table_context import table_result


def _case():
    result, brief = table_result()
    page = result.document.pages[0]
    table = page.tables[0]
    table.column_periods = [None, '6M2023', '6M2024']
    table.column_audit_statuses = ['unknown', 'unaudited', 'unknown']
    table.raw_header_lines.append('(unaudited)')
    table.bbox = (0, 100, 300, 160)
    page.text = '\n'.join(table.raw_header_lines) + '\nProgramme fees . . . 1,250 1,475'
    page.text_blocks = [{'lines': [
        {'text': 'Six months ended June 30,', 'bbox': [80, 0, 240, 10]},
        {'text': '2023', 'bbox': [100, 20, 120, 30]},
        {'text': '2024', 'bbox': [200, 20, 220, 30]},
        {'text': '(unaudited)', 'bbox': [90, 50, 130, 60]},
    ]}]
    brief.items[0].evidence[0].text = page.text
    return result, brief


def test_scope_keeps_positioned_annotation_on_its_own_column():
    result, brief = _case()
    inventory = source_audit_scope(brief.items[0], result)
    assert [(c['period'], c['status']) for c in inventory[0]['columns']] == [
        ('6M2023', 'unaudited'), ('6M2024', 'unknown')]
    assert inventory[0]['literal_audit_header_lines'] == ['(unaudited)']
    assert inventory[0]['source_table_confidence'] == result.document.pages[0].tables[0].confidence


@pytest.mark.parametrize('status', ['audited', 'unaudited'])
@pytest.mark.parametrize('period', ['six months ended June 30, 2024', '1H2024', '6M2024'])
def test_unmarked_period_supports_neither_audited_nor_unaudited(status, period):
    result, brief = _case()
    brief.items[0].text = f'Programme fees were USD 1,475 thousand in the {status} {period}.'
    assert audit_status_errors(brief.items[0], result)


@pytest.mark.parametrize('text', [
    'Programme fees were USD 1,250 thousand in the unaudited six months ended June 30, 2023.',
    'Programme fees were USD 1,250 thousand in 6M2023 (unaudited).',
    'Programme fees were USD 1,250 thousand at June 30, 2023 (unaudited).',
])
def test_genuinely_qualified_period_retains_its_status(text):
    result, brief = _case()
    brief.items[0].text = text
    assert not audit_status_errors(brief.items[0], result)


def test_explicit_conflicting_status_is_rejected():
    result, brief = _case()
    brief.items[0].text = 'Programme fees were USD 1,250 thousand in audited 6M2023.'
    assert audit_status_errors(brief.items[0], result)


@pytest.mark.parametrize('change', ['metadata', 'geometry', 'partial_row', 'uncited_label'])
def test_unverified_metadata_does_not_grant_status(change):
    result, brief = _case()
    page, table = result.document.pages[0], result.document.pages[0].tables[0]
    if change == 'metadata':
        table.column_audit_statuses = ['unknown', 'unknown', 'unaudited']
    elif change == 'geometry':
        page.text_blocks = []
    elif change == 'partial_row':
        brief.items[0].evidence[0].text = 'Programme fees . . . 1,250'
    else:
        brief.items[0].evidence[0].text = 'Programme fees . . . 1,250 1,475'
    brief.items[0].text = 'Programme fees were USD 1,475 thousand in unaudited 6M2024.'
    inventory = source_audit_scope(brief.items[0], result)
    assert all(c['status'] == 'unknown' for t in inventory for c in t['columns'])
    if change != 'partial_row':
        assert audit_status_errors(brief.items[0], result)


def test_competing_source_bindings_do_not_resolve_ambiguity_by_convenience():
    result, brief = _case()
    other = result.document.pages[0].tables[0].model_copy(deep=True)
    other.table_id = 'other'
    other.column_audit_statuses = ['unknown'] * 3
    result.document.pages[0].tables.append(other)
    brief.items[0].text = 'Programme fees were USD 1,250 thousand in unaudited 6M2023.'
    assert audit_status_errors(brief.items[0], result)


def test_unrelated_forecast_qualification_is_left_to_semantic_review():
    result, brief = _case()
    brief.items[0].text = 'The unaudited forecast for 2024 is preliminary; the table reports programme fees.'
    assert not audit_status_errors(brief.items[0], result)
    result.document.pages[0].tables = []
    brief.items[0].text = 'The source reports that its 2024 financial statements were unaudited.'
    assert source_audit_scope(brief.items[0], result) == []
    assert not audit_status_errors(brief.items[0], result)


def test_review_gets_column_scope_and_cannot_accept_an_invented_qualification():
    result, brief = _case()
    brief.items[0].text = 'Programme fees were USD 1,475 thousand in unaudited 6M2024.'
    class Gateway:
        def generate_structured(self, messages, schema, **kwargs):
            row = json.loads(messages[1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])[0]
            assert row['source_audit_scope'][0]['columns'][1]['status'] == 'unknown'
            return schema(items=[dict(index=0, accepted=True, reason='Accepted.',
                                     numeric_comparison=False, comparisons=[])])
    errors = meaning_validator(Gateway(), result=result)(brief)
    assert any('source column support' in error for error in errors[0])


def test_meaning_patch_cannot_add_status_from_ungrounded_reviewer_feedback():
    result, brief = _case()
    class Gateway:
        def generate_structured(self, messages, schema, **kwargs):
            assert 'Unknown supports neither' in messages[0]['content']
            return schema(item_0={'text': brief.items[0].text.replace(
                'the six months', 'the unaudited six months')})
    def review(current):
        return {} if 'unaudited' in current.items[0].text else {0: ['Missing unaudited qualification.']}
    audit = {}
    corrected = correct_new_meaning_errors(Gateway(), brief, result=result,
        excerpts={1: result.document.pages[0].text}, topics=[], source_context={},
        evidence_catalog=None, semantic_validator=review, audit=audit)
    assert corrected is None
    assert audit['post_source_meaning_correction']['status'] == 'rejected'
    assert any('source column support' in error
               for error in audit['post_source_meaning_correction']['errors_after'])


@pytest.mark.parametrize('box', [None, 'invalid', [1, 2, 3], [1, 2, 3, float('nan')],
                               [1, 2, 'x', 4], [10, 20, 5, 30]])
def test_malformed_geometry_is_unknown_not_a_crash(box):
    result, brief = _case()
    result.document.pages[0].text_blocks[0]['lines'][-1]['bbox'] = box
    assert all(c['status'] == 'unknown' for t in source_audit_scope(brief.items[0], result)
               for c in t['columns'])


@pytest.mark.parametrize('wrap', [False, True])
def test_explicit_cited_prose_can_qualify_its_own_period_alongside_an_unmarked_grid(wrap):
    result, brief = _case()
    source = 'The six months ended June 30, 2024 figures' + ('\n' if wrap else ' ') + 'were unaudited.'
    result.document.pages[0].text += '\n' + source
    from adaptive_document_agent.models.executive_brief import BriefQuote
    brief.items[0].evidence.append(BriefQuote(page=1, text=source))
    brief.items[0].text = 'Programme fees were USD 1,475 thousand in unaudited 6M2024.'
    assert not audit_status_errors(brief.items[0], result)
    brief.items[0].text = brief.items[0].text.replace('unaudited', 'audited')
    assert audit_status_errors(brief.items[0], result)


@pytest.mark.parametrize('source', [
    'No audited 6M2024 figures are available in this report.',
    'We cannot confirm whether the 6M2024 figures were audited.',
    'The 6M2024 figures were not audited.',
    'If the 6M2024 figures were audited, they would be available.',
    'The 6M2024 figures may be audited.',
])
def test_negative_uncertain_or_conditional_prose_cannot_grant_assurance(source):
    result, brief = _case()
    from adaptive_document_agent.models.executive_brief import BriefQuote
    result.document.pages[0].text += '\n' + source
    brief.items[0].evidence.append(BriefQuote(page=1, text=source))
    brief.items[0].text = 'Programme fees were USD 1,475 thousand in audited 6M2024.'
    assert audit_status_errors(brief.items[0], result)


@pytest.mark.parametrize('source_label', ['1H2023', 'H12023', '6M2023'])
@pytest.mark.parametrize('audience_label', ['1H2023', 'H12023', '6M2023'])
def test_first_half_labels_retain_exact_source_key_and_equivalent_aliases(source_label, audience_label):
    result, brief = _case()
    result.document.pages[0].tables[0].column_periods[1] = source_label
    brief.items[0].text = f'Programme fees were USD 1,250 thousand in unaudited {audience_label}.'
    assert not audit_status_errors(brief.items[0], result)


@pytest.mark.parametrize('audience_label', ['1H2023', 'H12023', '6M2023'])
def test_second_half_source_does_not_supply_first_half_assurance(audience_label):
    result, brief = _case()
    result.document.pages[0].tables[0].column_periods[1] = '2H2023'
    brief.items[0].text = f'Programme fees were USD 1,250 thousand in unaudited {audience_label}.'
    assert audit_status_errors(brief.items[0], result)


def test_period_metadata_cannot_move_a_positioned_status_to_a_different_source_year():
    result, brief = _case()
    result.document.pages[0].tables[0].column_periods = [None, '6M2024', '6M2023']
    brief.items[0].text = 'Programme fees were USD 1,475 thousand in unaudited 6M2024.'
    assert audit_status_errors(brief.items[0], result)


@pytest.mark.parametrize('audience_label', ['1H2023', 'H12023'])
def test_six_month_december_source_does_not_establish_first_half_status(audience_label):
    result, brief = _case()
    page = result.document.pages[0]
    page.text = page.text.replace('June 30', 'December 31')
    page.tables[0].raw_header_lines = [line.replace('June 30', 'December 31')
                                     for line in page.tables[0].raw_header_lines]
    page.text_blocks[0]['lines'][0]['text'] = 'Six months ended December 31,'
    brief.items[0].evidence[0].text = page.text
    brief.items[0].text = f'Programme fees were USD 1,250 thousand in unaudited {audience_label}.'
    assert source_audit_scope(brief.items[0], result)[0]['columns'][0]['status'] == 'unaudited'
    assert audit_status_errors(brief.items[0], result)
