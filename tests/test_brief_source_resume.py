import json

import pytest

from adaptive_document_agent.agent.brief_review_checkpoint import context_key
from adaptive_document_agent.agent.brief_source_resume import retained_source_pages
from adaptive_document_agent.models import ValidationIssue
from tests.test_brief_semantic_repair import result_for


def checkpoint(result, pages=(4, 2, 7, 1), companions=(7,)):
    result.validation_warnings.append(ValidationIssue(code='executive_brief_review_checkpoint',
        stage='report', message=json.dumps(dict(environment_key=context_key(None, None, result),
            source_context=dict(source_excerpt_scope=[dict(page=p) for p in pages],
                                companion_context_pages=list(companions)),
            checked={'0': ['Rejected copy still owns its retrieval choices.']}))))


def test_identical_environment_retains_primary_order_but_no_verdict():
    result = result_for(['Revenue was USD 12 million.'])
    checkpoint(result)
    assert retained_source_pages(result, {1, 2, 4, 7}) == [4, 2]
    result.document.sha256 = 'changed'
    assert retained_source_pages(result, {1, 2, 4, 7}) is None


@pytest.mark.parametrize('change', ['missing_page', 'no_boundary', 'duplicate', 'too_many'])
def test_unproven_or_invalid_primary_selection_requires_new_retrieval(change):
    result = result_for(['Revenue was USD 12 million.'])
    if change == 'no_boundary':
        checkpoint(result, companions=())
    elif change == 'duplicate':
        checkpoint(result, pages=(4, 4, 7))
    elif change == 'too_many':
        checkpoint(result, pages=(*range(11), 20), companions=(20,))
    else:
        checkpoint(result)
    assert retained_source_pages(result, {1, 4, 7} if change == 'missing_page' else set(range(30))) is None
