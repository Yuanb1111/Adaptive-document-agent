"""Writers and final reviewers need the same carry-over source paragraphs."""
import json

import pytest

from adaptive_document_agent.agent import retained_analysis as retained
from adaptive_document_agent.agent.retained_analysis_review import review_retained_analysis, review_complete
from adaptive_document_agent.agent.retained_page_sources import page_sources
from adaptive_document_agent.models import DocumentPage
from tests.test_retained_source_citations import fixture
from tests.test_retained_analysis_v216 import gateway, verdict


def source_packet():
    result, _, selection = fixture()
    result.document.pages.extend([
        DocumentPage(page_number=233, text='The preceding paragraph supplies the source period.'),
        DocumentPage(page_number=235, text='The next paragraph supplies a material qualification.')])
    result.document.page_count = max(result.document.page_count, 235)
    return result, selection


def test_authoring_packet_retains_adjacent_original_pages_without_expanding_numeric_rows():
    result, _ = source_packet()
    context = retained.selection_context(result, source_authoring=True)
    legacy = page_sources(result, retained.findings(result, allow_new_copy=True), include_neighbors=False)
    assert {p['page'] for p in context['source_pages']} == {233, 234, 235}
    assert {p['page'] for p in legacy['source_pages']} == {234}
    assert context['source_rows'] == legacy['source_rows']


def test_table_discussion_continuation_is_available_to_writer_and_final_reviewer():
    from adaptive_document_agent.agent.retained_analysis_review import review_context
    result,selection=source_packet()
    result.document.pages.append(DocumentPage(page_number=236,
        text='The discussion continues with a material limiting qualification.'))
    result.document.page_count=236
    context=retained.selection_context(result,source_authoring=True)
    assert 236 in {p['page'] for p in context['source_pages']}
    from adaptive_document_agent.models.executive_brief import BriefQuote
    selection.decisions[0].page.context_evidence=[BriefQuote(page=235,
        text='The next paragraph supplies a material qualification.')]
    retained.select_retained_analysis(gateway([selection.model_dump(),dict(
        accepted=True,reason='Synthetic complete original discussion.')]),result)
    result.presentation_plan=retained.compile_retained_analysis(result)
    assert {p['page'] for p in review_context(result)['source_pages']} <= {
        p['page'] for p in context['source_pages']}


def test_related_series_neighbor_context_matches_final_review_without_numeric_expansion():
    from adaptive_document_agent.agent.retained_analysis_review import review_context
    result,selection=source_packet()
    # Another period in the same comparable series has its own raw table and
    # adjacent source qualification. It is context, not a new allowed row.
    original=result.observations[0]
    result.observations.append(original.model_copy(update=dict(id='related-period',period='FY2026',
        table_id='related-table',value=600000000,raw_value='600,000',evidence=[
            original.evidence[0].model_copy(update=dict(page=237,table_id='related-table'))])))
    result.document.pages.extend([DocumentPage(page_number=236,text='Material source qualification.'),
        DocumentPage(page_number=237,text='Complete related source table.')])
    result.document.page_count=237
    context=retained.selection_context(result,source_authoring=True)
    assert 236 in {p['page'] for p in context['source_pages']}
    assert 'related-period' not in {row['id'] for row in context['source_rows']}
    retained.select_retained_analysis(gateway([selection.model_dump(),dict(
        accepted=True,reason='Synthetic complete source context.')]),result)
    result.presentation_plan=retained.compile_retained_analysis(result)
    assert {p['page'] for p in review_context(result)['source_pages']} <= {
        p['page'] for p in retained.selection_context(result,source_authoring=True)['source_pages']}


def test_legacy_selection_transport_is_not_publication_approval_for_changed_neighbor():
    result, selection = source_packet()
    retained.select_retained_analysis(gateway([selection.model_dump(),
        dict(accepted=True, reason='Synthetic selection protocol check.')]), result)
    warning = next(w for w in reversed(result.validation_warnings) if w.code == retained.SELECTION_CODE)
    record = json.loads(warning.message)
    context = retained.selection_context(result)
    anchors = page_sources(result, retained.findings(result, allow_new_copy=True), include_neighbors=False)
    record['input_fingerprint'] = retained.fingerprint({**context, 'source_pages': anchors['source_pages']})
    warning.message = json.dumps(record)
    assert retained.selection_input_matches(record, context, result)
    result.presentation_plan = retained.compile_retained_analysis(result)
    assert not review_complete(result)
    review_retained_analysis(gateway([verdict(result)]), result)
    assert review_complete(result)
    result.document.pages[-1].text += ' A changed source limitation.'
    assert not review_complete(result)
    result.observations[0].raw_value = '999999'
    assert not retained.selection_input_matches(record, retained.selection_context(result), result)
