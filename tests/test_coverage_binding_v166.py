"""Completed coverage must survive only source-bound, reviewed changes."""
import json
from copy import deepcopy

import pytest

from adaptive_document_agent.models import ValidationIssue
from adaptive_document_agent.agent.coverage_review_binding import source_fingerprint, completed_review_is_current
from adaptive_document_agent.agent.coverage_delta_review import _merge
from adaptive_document_agent.agent.topic_coverage_review import TopicCoverageReview
from tests.test_coverage_merge_encoding import _fixture


def fixture():
    result, lookup, selected, _ = _fixture()
    result.presentation_topics = selected
    audit = dict(source_fingerprint=source_fingerprint(lookup), review=selected.model_dump(mode='json'))
    return result, lookup, audit


def test_completed_review_expires_on_source_change():
    result, lookup, audit = fixture()
    assert completed_review_is_current(result, audit, lookup)
    next(iter(lookup.values()))[0].raw_value = 'Changed source value'
    assert not completed_review_is_current(result, audit, lookup)


def test_unreviewed_omission_does_not_inherit_coverage_success():
    result, lookup, audit = fixture()
    result.presentation_topics.topics = []
    assert not completed_review_is_current(result, audit, lookup)


@pytest.mark.parametrize('accepted', [True, False])
def test_budget_changes_need_complete_independent_omission_review(accepted):
    result, lookup, audit = fixture()
    original = deepcopy(audit['review'])
    ids = {sid for t in original['topics'] for sid in t['series_ids']}
    result.presentation_topics.topics = []
    budget = dict(original_selection=original, attempts=[dict(status='accepted',
        applied_selection=dict(topics=[]), independent_review=dict(accepted=accepted),
        review_target=dict(decisions=[dict(series_id=sid, include=False,
            reason='The model judged this comparison redundant against retained conclusions.') for sid in ids]))])
    result.validation_warnings.append(ValidationIssue(code='presentation_physical_budget_review',
        stage='presentation', severity='info', message=json.dumps(budget)))
    assert completed_review_is_current(result, audit, lookup) is accepted


def test_one_correction_receives_both_decision_and_source_errors():
    result, lookup, selected, _ = _fixture()
    extra = selected.topics[0].series_ids[0]
    reply = TopicCoverageReview(topics=selected.topics, coverage_decisions=[dict(
        series_id=extra, decision='include', reason='Already selected evidence.')])
    def invalid(*args, **kwargs):
        raise ValueError('Unsupported date scope')
    with pytest.raises(ValueError) as error:
        _merge(reply, selected, [], lookup, set(), invalid)
    assert 'unexpected' in str(error.value) and extra in str(error.value)
    assert 'Unsupported date scope' in str(error.value)
