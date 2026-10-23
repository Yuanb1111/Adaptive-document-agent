"""Source review capacity recovery never substitutes for fresh semantic approval."""

from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.source_integration_review import (
    SourceIntegrationDraft, SourceIntegrationReview, review_supplementary_sources,
    resolved_source_check_ids,
)
from adaptive_document_agent.services.pipeline_completion import (
    is_complete, is_reporting_ready, require_source_integration, source_review_complete,
)
from tests.test_budget_output_v145 import gateway, response
from tests.test_executive_brief import payload
from tests.test_source_integration_v166 import Gateway, fixture


LIMITS = (8192, 16384)
TRUNCATED_DRAFT = '{"additions":[{"text":"TRUNCATED_SOURCE_DRAFT_SENTINEL'
TRUNCATED_REVIEW = '{"verdicts":[{"reason":"TRUNCATED_SOURCE_REVIEW_SENTINEL'


def _outputs(constraint):
    draft = SourceIntegrationDraft(
        additions=payload(constraint, 12, "Contract risk")["items"],
        decisions=[dict(
            section_id="contracts", disposition="include",
            reason="The disclosed cancellation right qualifies future demand certainty.",
            evidence=[dict(page=12, text=constraint)], brief_item_indexes=[1],
        )],
    )
    review = SourceIntegrationReview(verdicts=[dict(
        section_id="contracts", accepted=True,
        reason="The added conclusion preserves the source cancellation condition.",
    )])
    return draft, review


def _audit(result):
    issue = next(issue for issue in reversed(result.validation_warnings)
                 if issue.code in {"source_integration_review", "source_integration_unresolved"})
    return issue.code, json.loads(issue.message)


@pytest.mark.parametrize("operation", ["draft", "review"])
def test_length_retry_uses_complete_identical_prompt_and_preserves_approved_draft(operation):
    result, constraint = fixture()
    original = result.executive_brief.model_copy(deep=True)
    source = deepcopy(result.document.model_dump())
    draft, review = _outputs(constraint)
    if operation == "draft":
        outputs = [response(TRUNCATED_DRAFT, finish="length"), response(draft), response(review)]
        retry_positions = (0, 1)
        expected_limits = [LIMITS[0], LIMITS[1], LIMITS[0]]
    else:
        outputs = [response(draft), response(TRUNCATED_REVIEW, finish="length"), response(review)]
        retry_positions = (1, 2)
        expected_limits = [LIMITS[0], LIMITS[0], LIMITS[1]]
    llm, client = gateway(outputs)

    result.executive_brief = review_supplementary_sources(llm, result, original)

    assert len(client.requests) == 3 and not client.outputs
    first, second = retry_positions
    assert client.requests[first][0] == client.requests[second][0]
    assert [kwargs["max_tokens"] for _, kwargs in client.requests] == expected_limits
    assert all(usage["stage"] == "report" for usage in llm.usage)
    assert result.executive_brief.items[0] == original.items[0]
    assert result.executive_brief.items[1:] == draft.additions
    assert result.document.model_dump() == source
    assert resolved_source_check_ids(result, result.executive_brief) == {"contracts"}
    assert source_review_complete(result) and is_complete(result)
    require_source_integration(result)
    code, audit = _audit(result)
    assert code == "source_integration_review" and len(audit["attempts"]) == 1
    attempt = audit["attempts"][0]
    capacity = attempt[f"{operation}_output_attempts"]
    assert [item["requested_max_tokens"] for item in capacity] == list(LIMITS)
    assert [item["status"] for item in capacity] == ["truncated", "response_received"]
    assert [item["capacity_retry"] for item in capacity] == [True, False]
    assert attempt["draft"] == draft.model_dump(mode="json")
    if operation == "review":
        assert len(attempt["draft_output_attempts"]) == 1
    # Broken JSON is useful local audit data, not material for the independent
    # semantic reviewer or an instruction to continue a partial response.
    final_review_messages = json.dumps(client.requests[-1][0])
    assert "TRUNCATED_SOURCE_DRAFT_SENTINEL" not in final_review_messages
    assert "TRUNCATED_SOURCE_REVIEW_SENTINEL" not in final_review_messages


@pytest.mark.parametrize("operation", ["draft", "review"])
def test_two_length_failures_exhaust_capacity_and_cannot_mark_result_complete(operation):
    result, constraint = fixture()
    original = result.executive_brief.model_copy(deep=True)
    draft, _ = _outputs(constraint)
    truncated = TRUNCATED_DRAFT if operation == "draft" else TRUNCATED_REVIEW
    outputs = ([] if operation == "draft" else [response(draft)]) + [
        response(truncated, finish="length"), response(truncated, finish="length")]
    llm, client = gateway(outputs)

    result.executive_brief = review_supplementary_sources(llm, result, original)

    assert result.executive_brief == original
    assert len(client.requests) == (2 if operation == "draft" else 3)
    assert client.requests[-2][0] == client.requests[-1][0]
    assert [kwargs["max_tokens"] for _, kwargs in client.requests[-2:]] == list(LIMITS)
    assert not resolved_source_check_ids(result, original)
    assert is_reporting_ready(result)  # The failed review must remain retryable.
    assert not source_review_complete(result) and not is_complete(result)
    with pytest.raises(ValueError):
        require_source_integration(result)
    code, audit = _audit(result)
    assert code == "source_integration_unresolved" and len(audit["attempts"]) == 1
    capacity = audit["attempts"][0][f"{operation}_output_attempts"]
    assert [item["status"] for item in capacity] == ["truncated", "truncated"]
    assert [item["capacity_retry"] for item in capacity] == [True, False]
    assert all(item["raw_response"] == truncated for item in capacity)


@pytest.mark.parametrize("operation", ["draft", "review"])
@pytest.mark.parametrize("finish", ["content_filter"])
def test_invalid_non_length_output_is_not_capacity_retried(operation, finish):
    result, constraint = fixture()
    original = result.executive_brief.model_copy(deep=True)
    draft, review = _outputs(constraint)
    outputs = ([] if operation == "draft" else [response(draft)]) + [
        response('{"incomplete":', finish=finish), response(review)]
    llm, client = gateway(outputs)

    result.executive_brief = review_supplementary_sources(llm, result, original)

    assert result.executive_brief == original
    assert len(client.requests) == (1 if operation == "draft" else 2)
    assert len(client.outputs) == 1  # No repair or new semantic answer was requested.
    code, audit = _audit(result)
    assert code == "source_integration_unresolved" and len(audit["attempts"]) == 1
    capacity = audit["attempts"][0][f"{operation}_output_attempts"]
    assert len(capacity) == 1 and capacity[0]["status"] == "invalid_format"
    assert capacity[0]["capacity_retry"] is False
    assert not source_review_complete(result) and not is_complete(result)


def test_new_accepted_review_supersedes_historical_unresolved_without_blocking_retry():
    result, constraint = fixture()
    original = result.executive_brief.model_copy(deep=True)
    result.executive_brief = review_supplementary_sources(
        Gateway(constraint, accept=False), result, original)
    assert _audit(result)[0] == "source_integration_unresolved"
    assert is_reporting_ready(result) and not is_complete(result)

    result.executive_brief = review_supplementary_sources(
        Gateway(constraint), result, result.executive_brief)

    assert any(issue.code == "source_integration_unresolved" for issue in result.validation_warnings)
    assert _audit(result)[0] == "source_integration_review"
    assert source_review_complete(result) and is_complete(result)
    require_source_integration(result)


@pytest.mark.parametrize("mutation", ["brief", "source", "check", "missing_brief"])
def test_stale_or_absent_current_brief_cannot_reuse_old_accepted_verdict(mutation):
    result, constraint = fixture()
    result.executive_brief = review_supplementary_sources(
        Gateway(constraint), result, result.executive_brief)
    assert is_complete(result)
    if mutation == "brief":
        result.executive_brief.items[0].text += " Changed interpretation."
    elif mutation == "source":
        result.document.pages[11].text += " Additional source qualification."
    elif mutation == "check":
        result.profile.source_coverage.checks[0].status = "incomplete"
    else:
        result.executive_brief = None

    assert is_reporting_ready(result)
    assert not source_review_complete(result) and not is_complete(result)
    with pytest.raises(ValueError):
        require_source_integration(result)


def test_checked_sources_without_any_integration_audit_require_review_before_completion():
    result, _ = fixture()
    assert all(check.status == "checked_found" for check in result.profile.source_coverage.checks)
    assert is_reporting_ready(result)
    assert not source_review_complete(result) and not is_complete(result)
    with pytest.raises(ValueError):
        require_source_integration(result)


def test_absent_supplementary_checks_do_not_add_a_review_requirement():
    result, _ = fixture()
    result.profile.source_coverage.checks = []
    result.executive_brief = None
    assert source_review_complete(result) and is_complete(result)
    require_source_integration(result)
    result.pipeline_state = "partial"
    assert source_review_complete(result)
    assert not is_reporting_ready(result) and not is_complete(result)
