"""Cross-page context propagation helpers."""

from adaptive_document_agent.models import Observation


def apply_context(observations: list[Observation], *, entity: str | None = None, period: str | None = None) -> list[Observation]:
    for observation in observations:
        if entity and not observation.entity:
            observation.entity = entity
        if period and not observation.period:
            observation.period = period
    return observations

