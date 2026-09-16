"""Dynamic coverage checks against model-discovered, user-aligned topics."""

from __future__ import annotations

import re
from dataclasses import dataclass

from adaptive_document_agent.models import DocumentProfile, Observation, ValidationIssue, ValidationReport
from adaptive_document_agent.document_model import display_metric_name, is_meaningful_metric


@dataclass(frozen=True)
class CoverageItem:
    topic: str
    status: str
    matched_metrics: tuple[str, ...]
    observation_count: int
    periods: tuple[str, ...]
    pages: tuple[int, ...]


def assess_coverage(profile: DocumentProfile, observations: list[Observation]) -> list[CoverageItem]:
    """Match discovered priority topics to retained evidence conservatively."""
    metric_groups: dict[str, list[Observation]] = {}
    display_names: dict[str, str] = {}
    for item in observations:
        if not is_meaningful_metric(item):
            continue
        name = display_metric_name(item)
        key = name.casefold()
        metric_groups.setdefault(key, []).append(item)
        display_names.setdefault(key, name)

    topics = list(dict.fromkeys(topic.strip() for topic in profile.metrics if topic.strip()))
    output: list[CoverageItem] = []
    for topic in topics:
        matched_keys = [key for key in metric_groups if _names_match(topic, key)]
        matched = [item for key in matched_keys for item in metric_groups[key]]
        supported = [item for item in matched if item.value is not None and item.evidence]
        if supported:
            status = "Covered"
        elif matched:
            status = "Partial"
        else:
            status = "Missing"
        output.append(
            CoverageItem(
                topic=topic,
                status=status,
                matched_metrics=tuple(sorted({display_names[key] for key in matched_keys})),
                observation_count=len(supported),
                periods=tuple(sorted({item.period for item in supported if item.period})),
                pages=tuple(sorted({source.page for item in supported for source in item.evidence})),
            )
        )
    return output


class CoverageValidator:
    def __init__(self, profile: DocumentProfile) -> None:
        self.profile = profile

    def validate(self, observations: list[Observation]) -> ValidationReport:
        report = ValidationReport()
        for item in assess_coverage(self.profile, observations):
            if item.status == "Missing":
                report.add(
                    ValidationIssue(
                        code="coverage_gap",
                        message=f"No retained observation matched the discovered priority topic '{item.topic}'.",
                        stage="coverage",
                        severity="warning",
                    )
                )
            elif item.status == "Partial":
                report.add(
                    ValidationIssue(
                        code="coverage_partial",
                        message=f"The topic '{item.topic}' was detected but lacks a numeric value with page evidence.",
                        stage="coverage",
                        severity="warning",
                    )
                )
        return report


def _names_match(left: str, right: str) -> bool:
    left_text, right_text = _normalise(left), _normalise(right)
    if not left_text or not right_text:
        return False
    if left_text == right_text or left_text in right_text or right_text in left_text:
        return True
    left_tokens, right_tokens = set(left_text.split()), set(right_text.split())
    smaller = min(len(left_tokens), len(right_tokens))
    return bool(smaller and len(left_tokens & right_tokens) / smaller >= 0.75)


def _normalise(value: str) -> str:
    return " ".join(re.findall(r"[\w%]+", value.casefold(), flags=re.UNICODE))
