"""Physical source addresses do not become reported values or license unrelated digits."""
from copy import deepcopy

import pytest

from adaptive_document_agent.models.executive_brief import ExecutiveBrief
from adaptive_document_agent.services.executive_brief import validate_executive_brief
from tests.test_executive_brief import result_for


@pytest.mark.parametrize('reference', ['Pages 1–3', 'pp. 1-3', 'Pages 1, 2 and 3', 'Page 2'])
def test_page_reference_is_checked_against_the_items_own_quotes(reference):
    result = result_for(['The company describes patent examples.'] * 3)
    brief = ExecutiveBrief(items=[dict(label='Patent scope', text=f'{reference}: patent examples are described.',
        evidence=[dict(page=p.page_number, text=p.text) for p in result.document.pages])])
    before = deepcopy((result, brief))
    assert not validate_executive_brief(brief, result)
    assert (result, brief) == before


@pytest.mark.parametrize('text', [
    'Pages 1–3 describe patent examples.', 'Pages 3–1 describe patent examples.',
    'Page 99 describes patent examples.', 'On page 1, 17 patents were granted.',
    'Page 1 describes HK$1 million of expenditure.', 'Page 1 reports 1% growth.',
])
def test_missing_reference_or_reused_citation_digits_do_not_license_claims(text):
    result = result_for(['The company describes patent examples.'] * 3)
    brief = ExecutiveBrief(items=[dict(label='Patent scope', text=text,
        evidence=[dict(page=1, text=result.document.pages[0].text)])])
    assert validate_executive_brief(brief, result)
