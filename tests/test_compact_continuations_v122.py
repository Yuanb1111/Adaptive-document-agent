from hashlib import sha256

from adaptive_document_agent.agent.compact_summary import CompactSummaryDraft, compact_input, expand_compact
from adaptive_document_agent.agent.summary_theme_layout import pack_theme_pages
from adaptive_document_agent.services.summary_validation import presentation_errors
from tests.test_compact_summary_v111 import fixture


def prepared():
    result, review, _ = fixture(1)
    text = ('The service requires staff training and customer acceptance before installation. ' * 22
            + 'Reported revenue was RMB100 million in 2023.')
    part = review.parts[0]
    part.source_text = text
    part.facts[0].text = part.facts[0].source_quote = text
    result.document.pages[0].text = text
    _, catalog = compact_input(review)
    draft = CompactSummaryDraft(pages=[dict(title='Service delivery', items=[dict(
        label='Delivery conditions', text=text, fact_ids=list(catalog))])])
    pages = pack_theme_pages(expand_compact(draft, catalog, review))
    return result, review, text, pages


def errors(result, review, pages):
    return presentation_errors(review, pages, result, validate_reading=False, verify_compact_review=False)


def test_long_compact_copy_retains_every_character_unit_and_binding():
    result, review, original, pages = prepared()
    items = [item for page in pages for item in page.items]
    assert len(items) > 1 and all(len(item.text) <= 1200 for item in items)
    assert ''.join(item.text for item in items) == original
    assert len({item.continuation_group for item in items}) == 1
    assert not errors(result, review, pages)


def test_missing_or_rewritten_continuation_cannot_pass_source_checks():
    result, review, _, pages = prepared()
    pages[-1].items[-1].text = pages[-1].items[-1].text.replace('RMB100', 'RMB999')
    assert any('continuation provenance' in e for e in errors(result, review, pages))
    items = [item for page in pages for item in page.items]
    digest = sha256(''.join(item.text for item in items).encode()).hexdigest()
    for item in items:
        item.continuation_digest = digest
    assert any('unsupported numeric' in e for e in errors(result, review, pages))
    pages.pop()
    assert any('continuation provenance' in e for e in errors(result, review, pages))
