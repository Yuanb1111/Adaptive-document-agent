"""Explain signed source conventions without altering extracted observations."""

from adaptive_document_agent.document_model import display_metric_name
from adaptive_document_agent.models import Observation
from adaptive_document_agent.validation.claim_validator import MetricSemanticFamily, classify_metric_semantic_family


def is_signed_expense_ratio(o: Observation) -> bool:
    return (o.value is not None and o.value < 0 and o.unit in {"percent", "percentage", "%"}
            and classify_metric_semantic_family(display_metric_name(o), o.metric_canonical)
            == MetricSemanticFamily.EXPENSE)


def signed_expense_display(o: Observation, default: str, *, with_unit: bool = True) -> str:
    if is_signed_expense_ratio(o):
        return f"{o.value:g}" + ("%" if with_unit else "")
    return default


def signed_expense_note(observations: list[Observation]) -> str:
    if any(is_signed_expense_ratio(o) for o in observations):
        return ("Expense ratios retain reported negative signs (deductions from revenue). "
                "A larger absolute ratio means greater expense intensity.")
    return ""
