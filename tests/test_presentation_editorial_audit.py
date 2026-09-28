"""Mechanical repair history survives fresh server-owned review findings."""

from adaptive_document_agent.services.presentation_editorial import stamp_editorial_review
from tests.test_p1_theme_planning import themed_result


def test_restamping_preserves_deduplicated_repairs_and_expires_old_findings():
    result = themed_result()
    plan = result.presentation_plan
    repairs = [
        "Slide revenue: aligned 6 duplicate observation references with a coherent source series",
        "Slide cost: restored the selected takeaway after source-bound share validation",
        "Bound ratio denominator to the explicit source definition on p. 3 for cost.",
    ]
    plan.editorial_notes = [*repairs, repairs[0],
        "revenue: The title only names the metric. State the supported finding or analytical question without adding unsupported numbers.",
        "Most analysis pages contain one chart. Review whether companion evidence answers the same question.",
        "[review:presentation_boilerplate] old: Replace the generic subtitle with the actual scope, caveat or finding supported by this page.",
    ]
    plan.editorial_status = "needs_review"
    stamp_editorial_review(plan, result, origin="model")
    assert plan.editorial_status == "ready"
    assert plan.editorial_notes == repairs
    snapshot = plan.model_dump()
    stamp_editorial_review(plan, result, origin="model")
    assert snapshot == plan.model_dump()


def test_current_review_is_regenerated_then_removed_after_copy_is_fixed():
    result = themed_result()
    plan, slide = result.presentation_plan, result.presentation_plan.slides[3]
    original = slide.message
    audit = "Slide revenue: added reported share values from the same source row"
    plan.editorial_notes = [audit]
    slide.message = "Evidence-backed comparison of retained reported values."
    stamp_editorial_review(plan, result, origin="model")
    assert plan.editorial_status == "needs_review"
    assert audit in plan.editorial_notes
    assert len([note for note in plan.editorial_notes if note.startswith("[review:")]) == 1
    snapshot = plan.model_dump()
    stamp_editorial_review(plan, result, origin="model")
    assert snapshot == plan.model_dump()
    slide.message = original
    stamp_editorial_review(plan, result, origin="model")
    assert plan.editorial_status == "ready"
    assert plan.editorial_notes == [audit]


def test_current_unresolved_period_prevents_ready_but_historical_warning_does_not():
    from adaptive_document_agent.models import PresentationTheme
    from adaptive_document_agent.services.presentation_period_scope import prepare_presentation_period_scope
    from tests.test_presentation_period_scope import _sample

    result = _sample(extra=False)
    plan = result.presentation_plan
    plan.themes = [PresentationTheme(id="operations", title="Operations", question="What changed?",
                                    rationale="Compare the reported movements.")]
    result.observations[0].period = "Unknown"
    prepare_presentation_period_scope(result)
    stamp_editorial_review(plan, result, origin="model")
    assert plan.editorial_status == "needs_review"
    assert any("[review:presentation_period_scope_unresolved]" in note for note in plan.editorial_notes)
    result.observations[0].period = "FY2021"
    stamp_editorial_review(plan, result, origin="model")
    assert plan.editorial_status == "ready"
    assert not any("[review:presentation_period_scope_unresolved]" in note for note in plan.editorial_notes)
    assert any(w.code == "presentation_period_scope_unresolved" for w in result.validation_warnings)
