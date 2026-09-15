"""Build and de-duplicate a global observation index."""

from collections.abc import Iterable

from adaptive_document_agent.models import Observation
from .index import DocumentIndex


class DocumentModelBuilder:
    def build(self, observations: Iterable[Observation]) -> DocumentIndex:
        unique: dict[tuple[object, ...], Observation] = {}
        for observation in observations:
            key = (
                (observation.metric_canonical or observation.metric_original).casefold(),
                observation.period,
                observation.entity,
                tuple(sorted(observation.dimensions.items())),
                observation.value,
                observation.unit,
                observation.currency,
            )
            existing = unique.get(key)
            if not existing or observation.confidence > existing.confidence:
                unique[key] = observation
            elif existing:
                existing.evidence.extend(item for item in observation.evidence if item not in existing.evidence)
        return DocumentIndex(unique.values())

