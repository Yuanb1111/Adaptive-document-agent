import json

import pytest

from adaptive_document_agent.agent import retained_analysis as retained
from adaptive_document_agent.agent import retained_analysis_review as publication
from adaptive_document_agent.agent.retained_audit_scope import verified_column_assurance
from adaptive_document_agent.agent.retained_selection_coverage import review_selection_coverage
from adaptive_document_agent.models import ExtractedTable, TableRow
from tests.test_retained_analysis_v216 import gateway, verdict
from tests.test_retained_source_citations import fixture as selection_fixture


@pytest.fixture
def positioned():
    result, _, selection = selection_fixture()
    page = result.document.pages[0]
    table_id = 'positioned-source'
    headers = ['Year ended December 31,', '2023 2024 2025', '(unaudited)']
    values = [o.raw_value for o in result.observations]
    page.text = '\n'.join([*headers, 'Revenue ' + ' '.join(values)])
    page.text_blocks = [{'lines': [
        {'text': headers[0], 'bbox': [80, 0, 340, 10]},
        {'text': '2023', 'bbox': [100, 20, 120, 30]},
        {'text': '2024', 'bbox': [200, 20, 220, 30]},
        {'text': '2025', 'bbox': [300, 20, 320, 30]},
        {'text': headers[2], 'bbox': [90, 50, 130, 60]},
    ]}]
    periods = [None, 'FY2023', 'FY2024', 'FY2025']
    statuses = ['unknown', 'unaudited', 'unknown', 'unknown']
    page.tables = [ExtractedTable(table_id=table_id, page=page.page_number,
        headers=['label', *periods[1:]], column_periods=periods, column_audit_statuses=statuses,
        raw_header_lines=headers, bbox=(0, 100, 350, 160),
        rows=[TableRow(cells=['Revenue', *values], page=page.page_number)])]
    for column, observation in enumerate(result.observations, 1):
        observation.table_id = table_id
        observation.row_id = 0
        observation.column_id = column
        observation.audited_status = statuses[column]
        observation.evidence[0].table_id = table_id
    return result, selection


@pytest.mark.parametrize('case', ['adjacent', 'genuine', 'no_geometry', 'wrong_cell', 'unstructured'])
def test_coverage_checks_the_requested_status_against_its_original_column(positioned, case):
    result, selection = positioned
    first, second, _ = result.observations
    iid = selection.ordered_insight_ids[0]
    issue = dict(insight_id=iid, reason='Add the source unaudited marker.')
    if case != 'unstructured':
        issue['assurance_changes'] = [dict(
            observation_id=first.id if case == 'genuine' else second.id, status='unaudited')]
    if case == 'no_geometry':
        result.document.pages[0].text_blocks = []
    if case == 'wrong_cell':
        result.document.pages[0].tables[0].rows[0].cells[2] = '999'
    context = retained.selection_context(result, source_authoring=True)
    context['copy_review_ids'] = [iid]
    response = dict(accepted=False, page_issues=[issue], reason=issue['reason'])
    mock = gateway([response])
    if case == 'adjacent':
        review_selection_coverage(mock, context, selection, result)
        bindings = verified_column_assurance(result, {first.id, second.id})
        assert (bindings[first.id]['column'], bindings[first.id]['status']) == (1, 'unaudited')
        assert (bindings[second.id]['column'], bindings[second.id]['status']) == (2, 'unknown')
        audit = json.loads(result.validation_warnings[-1].message)
        assert audit['review']['page_issues'] == [issue]
        assert audit['effective_review']['accepted']
        assert not audit['final_presentation_approval']
    else:
        with pytest.raises(ValueError, match='Add the source unaudited marker'):
            review_selection_coverage(mock, context, selection, result)


@pytest.mark.parametrize('omissions_accepted', [True, False])
def test_final_review_keeps_real_omissions_actionable(positioned, omissions_accepted):
    result, selection = positioned
    accepted = dict(accepted=True, reason='The selection is sufficient.')
    retained.select_retained_analysis(gateway([selection.model_dump(), accepted]), result)
    result.presentation_plan = retained.compile_retained_analysis(result)
    response = verdict(result, accepted=False)
    response['omissions_accepted'] = omissions_accepted
    response['verdicts'][0]['assurance_changes'] = [
        dict(observation_id=result.observations[1].id, status='unaudited')]
    mock = gateway([response])
    if omissions_accepted:
        publication.review_retained_analysis(mock, result)
        assert publication.review_complete(result)
        assert not json.loads(result.validation_warnings[-1].message)['review']['verdicts'][0]['accepted']
    else:
        with pytest.raises(ValueError, match='Omitted findings'):
            publication.review_retained_analysis(mock, result)
        assert not publication.review_complete(result)
