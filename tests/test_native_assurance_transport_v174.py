"""First-draft transport must retain assurance ownership when periods coincide."""
import json

from adaptive_document_agent.agent.brief_native_transport import source_quantity_options
from adaptive_document_agent.models import ExtractedTable
from adaptive_document_agent.models.table import TableRow
from tests.test_report_audit_scope_v174 import fixture, Gateway
from adaptive_document_agent.agent.report_audit_scope import review_report_audit_scope


def scoped_grid():
    result, binding = fixture()
    # Amount and percentage share a date and source row. Only the exact amount
    # has the independently reviewed link to an audited statement.
    text = ('Example Group consolidated results for 6M2025.\n'
            'Amount Margin\nRMB thousands\nRevenue 120,462 20.0%')
    result.document.pages[0].text = text
    result.document.pages[0].tables = [ExtractedTable(table_id='amounts', page=1,
        headers=['Metric', 'Amount', 'Margin'], column_periods=[None, '6M2025', '6M2025'],
        column_audit_statuses=['unknown', 'unknown', 'unknown'],
        raw_header_lines=['Example Group consolidated results for 6M2025.', 'Amount Margin', 'RMB thousands'],
        rows=[TableRow(cells=['Revenue', '120,462', '20.0%'], page=1)])]
    binding['target_quote']['text'] = text
    review_report_audit_scope(Gateway(binding), result)
    return result, {1: text}, {'grid': {'page': 1, 'text': text}}


def test_same_period_amount_and_percentage_keep_distinct_exact_assurance_addresses():
    result, excerpts, blocks = scoped_grid()
    rows = source_quantity_options(result, excerpts, blocks)
    statuses = [status for row in rows for status in row.get('source_period_statuses', [])]
    assert len(statuses) == 2
    by_column = {status['source_column_index']: status for status in statuses}
    assert by_column[1]['status'] == 'audited'
    assert by_column[2]['status'] == 'unknown'
    assert all(status['period'] == '6M2025' and status['source_page'] == 1
               and status['source_table_id'] == 'amounts'
               and status['source_row_labels'] == ['Revenue'] for status in statuses)
    assert by_column[1]['source_column_label'].casefold() == 'amount'
    assert by_column[2]['source_column_label'].casefold() == 'margin'
    assert 'date_aliases' in by_column[1] and 'binding_basis' in by_column[1]
    assert result.observations[0].audited_status == result.observations[1].audited_status == 'unknown'


def test_small_budget_never_sends_a_status_with_its_measure_address_removed():
    result, excerpts, blocks = scoped_grid()
    rows = source_quantity_options(result, excerpts, blocks, character_limit=240)
    assert len(json.dumps(rows, ensure_ascii=False)) <= 240
    assert not any(row.get('source_period_statuses') for row in rows)
    # The literal blocks still retain the source. Omission is not a period-wide
    # assertion and cannot certify the percentage using the amount's status.
    assert '120,462' in blocks['grid']['text'] and '20.0%' in blocks['grid']['text']


def test_early_large_page_cannot_starve_later_page_quantities_and_statuses(monkeypatch):
    from adaptive_document_agent.agent import brief_native_transport as transport
    from tests.test_executive_brief import result_for
    result = result_for(['First source page.', 'Later source page.'])
    excerpts = {page.page_number: page.text for page in result.document.pages}
    blocks = {f'p{page}': {'page': page, 'text': text} for page, text in excerpts.items()}

    def amounts(original, *_):
        page = original['items'][0]['evidence'][0]['page']
        return {'item_0': [{'amount_text': f'USD {page * 1000 + i} thousand'} for i in range(80)]}

    def statuses(item, *_):
        page = item.evidence[0].page
        return [dict(source_page=page, source_table_id=f'table-{page}',
            source_row_labels=['Source measure'], source_column_index=i,
            source_column_label='Amount', period='FY2025', date_aliases=[],
            status='audited', allowed_spellings=['FY2025 (audited)'], binding_basis='reviewed')
            for i in range(1, 41 if page == 1 else 2)]

    monkeypatch.setattr(transport, 'native_quantity_options', amounts)
    monkeypatch.setattr(transport, 'audit_status_options', statuses)
    rows = source_quantity_options(result, excerpts, blocks, character_limit=1800)
    assert len(json.dumps(rows, ensure_ascii=False)) <= 1800
    assert {row['page'] for row in rows} == {1, 2}
    later = next(row for row in rows if row['page'] == 2)
    assert later['quantities'] and later['source_period_statuses']
    assert later['source_period_statuses'][0]['source_table_id'] == 'table-2'


def test_status_coalescing_keeps_columns_and_conflicting_rows_separate():
    from adaptive_document_agent.agent.brief_native_transport import _coalesce_statuses
    base = dict(source_page=1, source_table_id='same-table', source_column_index=1,
                period='FY2025', status='audited')
    rows = [{**base, 'source_row_labels': ['Revenue']},
            {**base, 'source_row_labels': ['Profit']},
            {**base, 'source_row_labels': ['Margin'], 'source_column_index': 2, 'status': 'unknown'},
            {**base, 'source_row_labels': ['Other measure'], 'status': 'unknown'}]
    grouped = _coalesce_statuses(rows)
    assert len(grouped) == 3
    assert grouped[0]['source_row_labels'] == ['Revenue', 'Profit']
    assert all('Margin' not in row['source_row_labels'] for row in grouped if row['status'] == 'audited')
