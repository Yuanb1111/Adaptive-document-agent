"""Coverage pages explain omissions while the complete audit stays unchanged."""

import json

import pytest

from adaptive_document_agent.models import PresentationPlan, PresentationTheme, ValidationIssue
from adaptive_document_agent.services.presentation_scope import scope_items
from tests.test_presentation_key_figures import _result


@pytest.mark.parametrize("title", ["Regional profitability", "Production capacity", "Customer satisfaction"])
def test_omitted_topic_keeps_subject_without_exposing_internal_validation_error(title):
    result = _result()
    result.presentation_plan = PresentationPlan(title="Review")
    diagnostic = json.dumps({
        "phase": "initial", "topic": {"id": "topic_private_id", "title": title},
        "error": "Topic topic_private_id contains unsupported numeric claims: ['998877']",
    })
    result.validation_warnings.append(ValidationIssue(
        code="presentation_topic_validation", stage="presentation", message=diagnostic,
    ))
    before = result.model_dump()

    items = scope_items(result)

    omitted = next(item for item in items if item.title == "Not covered: " + title)
    assert "source evidence" in omitted.text
    visible = "\n".join(item.title + "\n" + item.text for item in items)
    assert "topic_private_id" not in visible
    assert "998877" not in visible
    assert "unsupported numeric claims" not in visible
    assert "diagnostics" not in visible and "JSON" not in visible
    assert result.model_dump() == before
    assert result.validation_warnings[-1].message == diagnostic


def test_restored_topic_does_not_keep_an_omission_notice():
    result = _result()
    result.presentation_plan = PresentationPlan(title="Review", themes=[PresentationTheme(
        id="restored", title="Service availability", question="What changed?", rationale="Source series",
    )])
    result.validation_warnings.append(ValidationIssue(
        code="presentation_topic_validation", stage="presentation", message=json.dumps({
            "phase": "initial", "topic": {"id": "restored", "title": "Service availability"},
            "error": "Original draft failed validation.",
        }),
    ))
    assert not any(item.title.startswith("Not covered:") for item in scope_items(result))
