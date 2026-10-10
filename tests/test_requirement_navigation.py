"""Long actual-entry navigation must not suppress independent report instructions."""
import json
from threading import Barrier, Lock
from types import SimpleNamespace

import pytest

from adaptive_document_agent.agent.report_requirements import interpret_requirements, appendix_pages
from adaptive_document_agent.agent.requirement_navigation import NavigationHeadings, navigation_batches
from adaptive_document_agent.models.customization import ReportRequirement, ReportRequirements, RequestedSection
from adaptive_document_agent.services.llm.exceptions import PrivacyViolationError, LLMTransportError
from tests.test_report_customization import document, table_requirement


def intent():
    tables = table_requirement()
    tables.sections, tables.resolution = [], 'ambiguous'
    return ReportRequirements(items=[tables, ReportRequirement(id='lang', kind='output_language',
        request_quote='Chinese body', description='Chinese body', language='Chinese')])


REQUEST = 'All Results tables; Chinese body'


def test_long_navigation_reaches_real_interpreter_and_compact_outline_binding():
    doc = document()
    doc.pages[0].text = 'Contents ' + 'untrusted source ' * 60_000
    calls = []
    def generate(messages, model, **kwargs):
        calls.append(messages)
        if len(calls) == 1:
            assert 'untrusted source' not in str(messages)
            return intent()
        assert len(str(messages)) < 60_000
        response = intent()
        response.items[0] = table_requirement()
        return response
    result = interpret_requirements(SimpleNamespace(generate_structured=generate), doc, REQUEST)
    assert len(calls) == 2 and not result.interpretation_error
    assert appendix_pages(result) == {2, 3}
    assert result.items[1].language == 'Chinese'


def test_opening_batches_preserve_all_characters_even_for_one_oversized_line():
    doc = document()
    doc.pages[0].text = 'Heading ' + '\\"source ' * 80_000
    batches = navigation_batches(doc)
    assert len(batches) > 1
    assert all(len(json.dumps(b, ensure_ascii=False)) <= 60_000 for b in batches)
    for page in doc.pages:
        records = [r for b in batches for r in b if r['page'] == page.page_number]
        assert ''.join(r['opening_text'] for r in records) == '\n'.join(page.text.splitlines()[:12])


@pytest.mark.parametrize('workers', [1, 2])
def test_complete_batched_navigation_is_supplied_before_final_binding(workers):
    doc = document()
    doc.outline = []
    doc.pages[0].text = 'Contents\n' + 'source ' * 90_000
    observed = []
    barrier, lock = Barrier(2), Lock()
    started = []
    def generate(messages, model, **kwargs):
        if model is NavigationHeadings:
            batch = json.loads(messages[-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
            with lock:
                started.append(1)
                first_pair = len(started) <= 2
            if workers == 2 and first_pair:
                barrier.wait(timeout=5)
            with lock:
                observed.extend(batch)
            return model(headings=[{'page': r['page'], 'title': r['opening_text'].splitlines()[0],
                'quote': r['opening_text'].splitlines()[0]} for r in batch if r['page'] in {2,4}])
        response = intent()
        if observed:
            assert len(started) == len(navigation_batches(doc))
            response.items[0].resolution = 'resolved'
            response.items[0].sections = [RequestedSection(title='Results', start_page=2, end_page=3,
                start_quote='Results', next_section_quote='Appendix')]
        return response
    result = interpret_requirements(SimpleNamespace(generate_structured=generate, discovery_workers=workers), doc, REQUEST)
    assert appendix_pages(result) == {2,3}
    assert len(result.navigation_audit) > 1
    assert {r['page'] for r in observed} == {1,2,3,4}
    assert ''.join(r['opening_text'] for r in sorted(observed, key=lambda r: r['opening_offset'])
                   if r['page']==1) == doc.pages[0].text


def test_location_failure_preserves_language_and_marks_only_chapter_ambiguous():
    calls = []
    def generate(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            return intent()
        raise LLMTransportError('unavailable')
    result = interpret_requirements(SimpleNamespace(generate_structured=generate), document(), REQUEST)
    assert result.items[1].resolution == 'resolved'
    assert result.items[1].language == 'Chinese'
    assert result.items[0].resolution == 'ambiguous' and not appendix_pages(result)
    assert not result.interpretation_error
    assert len(calls) == 2


def test_resolution_cannot_drop_or_change_independent_user_intent():
    calls = []
    def generate(*a, **k):
        calls.append(1)
        response = intent()
        if len(calls) > 1:
            response.items[0] = table_requirement()
            response.items[1].language = 'English'
        return response
    result = interpret_requirements(SimpleNamespace(generate_structured=generate), document(), REQUEST)
    assert not appendix_pages(result)
    assert result.items[1].language == 'Chinese'
    assert len(calls) == 3


def test_location_privacy_rejection_propagates():
    calls = []
    def generate(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            return intent()
        raise PrivacyViolationError('cloud forbidden')
    with pytest.raises(PrivacyViolationError):
        interpret_requirements(SimpleNamespace(generate_structured=generate), document(), REQUEST)
