"""Reuse exact deterministic work, never stale source or semantic approval."""
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from unittest.mock import Mock

import pytest

from adaptive_document_agent.agent import report_audit_scope as audit
from adaptive_document_agent.services import source_quotes, validation_cache as memo
from tests.test_report_audit_scope_v174 import fixture, Gateway


def approved():
    result, binding = fixture()
    audit.review_report_audit_scope(Gateway(binding), result)
    return result


def test_same_source_validates_once_without_mutating_export_or_returned_approval(monkeypatch):
    result = approved()
    original = result.model_dump_json()
    verify = Mock(wraps=audit._validate_accepted_record)
    monkeypatch.setattr(audit, '_validate_accepted_record', verify)
    with memo.validation_cache_scope():
        first = audit.reviewed_audit_bindings(result)
        assert first['amount'].status == 'audited'
        first['amount'].status = 'unaudited'
        with memo.validation_cache_scope():
            assert audit.reviewed_audit_bindings(result)['amount'].status == 'audited'
        audit.require_report_audit_scope(result)
        assert verify.call_count == 1
    assert result.model_dump_json() == original
    with memo.validation_cache_scope():
        assert audit.reviewed_audit_bindings(result)
    assert verify.call_count == 2


@pytest.mark.parametrize('change', ['text', 'value', 'geometry', 'check', 'pages', 'ledger'])
def test_source_or_audit_change_invalidates_accepted_validation(change, monkeypatch):
    result = approved()
    verify = Mock(wraps=audit._validate_accepted_record)
    monkeypatch.setattr(audit, '_validate_accepted_record', verify)
    with memo.validation_cache_scope():
        assert audit.reviewed_audit_bindings(result)
        if change == 'text':
            result.document.pages[-1].text += ' A changed source body.'
        elif change == 'value':
            result.observations[0].value += 1
        elif change == 'geometry':
            result.document.pages[4].text_blocks = [dict(lines=[dict(
                text='Six months ended 30 June 2025.', bbox=[1, 1, 150, 15]), dict(
                text='Revenue 120,462.', bbox=[170, 1, 320, 15])])]
        elif change == 'check':
            result.profile.source_coverage.checks[0].reason += ' Changed source-check meaning.'
        elif change == 'pages':
            result.document.page_count += 1
        else:
            result.validation_warnings[-1].message = '{}'
        assert not audit.reviewed_audit_bindings(result)
        assert verify.call_count == 2


def test_new_targets_and_later_failure_still_block_final_gate():
    from adaptive_document_agent.models import ValidationIssue
    result, binding = fixture()
    result.observations.append(result.observations[0].model_copy(deep=True,
        update={'id': 'new', 'row_id': 2}))
    audit.review_report_audit_scope(Gateway(binding), result)
    with memo.validation_cache_scope():
        audit.require_report_audit_scope(result)
        # Source data and approval remain identical; only the current target
        # selection changes. The final gate must check it outside the cache.
        result.presentation_plan.themes[0].observation_ids.append('new')
        with pytest.raises(ValueError, match='unfinished or stale'):
            audit.require_report_audit_scope(result)
        result.validation_warnings.append(ValidationIssue(code='report_audit_scope_unresolved',
            stage='report', message='A later review failed.'))
        assert not audit.reviewed_audit_bindings(result)


def test_quote_cache_keeps_literal_signs_values_and_words_and_releases_session(monkeypatch):
    normalize = Mock(wraps=source_quotes._normalize_quote)
    monkeypatch.setattr(source_quotes, '_normalize_quote', normalize)
    text = 'Revenue . . . RMB (120.5) million; “unaudited” 2025.'
    with memo.validation_cache_scope():
        for _ in range(20):
            assert source_quotes.normalize_quote(text) == 'revenue rmb (120.5) million; "unaudited" 2025.'
        assert normalize.call_count == 1
        assert source_quotes.normalize_quote(text.replace('120.5', '120.6')) != source_quotes.normalize_quote(text)
    source_quotes.normalize_quote(text)
    assert normalize.call_count == 3
    assert memo._active.get() is None


def test_quote_cache_is_bounded_and_excludes_oversized_text():
    with memo.validation_cache_scope():
        for i in range(600):
            source_quotes.normalize_quote(str(i) + ' source' * 4000)
        cache = memo._active.get()
        assert len(cache['text']) <= memo.MAX_TEXT_ENTRIES
        assert cache['chars'] <= memo.MAX_TOTAL_TEXT_CHARS
        size = len(cache['text'])
        source_quotes.normalize_quote('x' * (memo.MAX_TEXT_CHARS + 1))
        assert len(cache['text']) == size
    assert cache['text'] == cache['audit'] == {}


def test_exception_and_copied_worker_context_do_not_leak_cache():
    with pytest.raises(RuntimeError):
        with memo.validation_cache_scope():
            source_quotes.normalize_quote('owned source')
            with ThreadPoolExecutor(1) as pool:
                assert pool.submit(copy_context().run, memo._current).result() is None
            raise RuntimeError('cancelled')
    assert memo._active.get() is None


def test_page_ranking_reuses_identical_inputs_and_returns_independent_results(monkeypatch):
    from adaptive_document_agent.services.company_discovery import CompanyProfileDiscovery as Discovery
    result, _ = fixture()
    score = Mock(wraps=Discovery.score_page)
    monkeypatch.setattr(Discovery, 'score_page', score)
    with memo.validation_cache_scope():
        pages = Discovery.rank_profile_pages(result.document, result.profile)
        count = score.call_count
        pages.clear()
        assert Discovery.rank_profile_pages(result.document, result.profile)
        assert score.call_count == count
        for mutate in (
            lambda: setattr(result.document.pages[0], 'text', 'Our business\nWe provide products.'),
            lambda: setattr(result.document.pages[0], 'page_number', 2),
            lambda: setattr(result.document, 'page_count', 8),
            lambda: result.profile.document_summary_pages.append(4),
        ):
            mutate()
            assert Discovery.rank_profile_pages(result.document, result.profile) == Discovery._rank_profile_pages(
                result.document, result.profile, 8)
            assert score.call_count == count + 2 * len(result.document.pages)
            count = score.call_count
        assert Discovery.rank_profile_pages(result.document, result.profile, 2) == Discovery._rank_profile_pages(
            result.document, result.profile, 2)
        assert score.call_count == count + 2 * len(result.document.pages)
        cache = memo._current()
        for size in range(12):
            Discovery.rank_profile_pages(result.document, result.profile, size)
        assert len(cache['ranking']) <= 8
    assert cache['ranking'] == {}


def test_empty_legacy_introduction_skips_retrieval_without_hiding_missing_dynamic_audit(monkeypatch):
    from adaptive_document_agent.models.presentation import CompanyProfile
    from adaptive_document_agent.services import company_summary
    result, _ = fixture()
    retrieve = Mock(side_effect=AssertionError('No legacy items to check'))
    monkeypatch.setattr(company_summary, 'summary_excerpts', retrieve)
    company = CompanyProfile()
    assert company_summary.validate_summary(company, result) == []
    # The early return must not suppress this pre-existing fail-closed check.
    company.summary_pages = [object()]
    assert company_summary.validate_summary(company, result) == [
        'Dynamic Summary slides require their complete reading/decision audit']
    retrieve.assert_not_called()


def test_endpoint_check_does_not_scan_catalog_without_endpoints(monkeypatch):
    from adaptive_document_agent.models import PresentationSlide
    from adaptive_document_agent.validation import scoped_narrative_values as endpoints
    result, _ = fixture()
    labels = Mock(wraps=endpoints._label_variants)
    monkeypatch.setattr(endpoints, '_label_variants', labels)
    slide = PresentationSlide(id='s', slide_type='analysis', title='Revenue and margin',
                              message='Revenue is RMB 120,462 thousand; margin is 20.0%.')
    assert endpoints.scoped_value_errors(slide, result.observations) == []
    labels.assert_not_called()
    slide.message = 'Revenue rose to 20.0.'
    assert endpoints.scoped_value_errors(slide, result.observations)
    assert labels.call_count == len(result.observations)
