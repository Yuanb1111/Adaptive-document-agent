"""Query index over observations; planners do not need raw PDF text."""

from collections import defaultdict
from collections.abc import Iterable

from adaptive_document_agent.models import Observation


class DocumentIndex:
    def __init__(self, observations: Iterable[Observation] = ()) -> None:
        self.observations = list(observations)
        self._by_id = {observation.id: observation for observation in self.observations}
        self._by_metric: dict[str, list[Observation]] = defaultdict(list)
        self._by_period: dict[str, list[Observation]] = defaultdict(list)
        for observation in self.observations:
            self._by_metric[self._metric_key(observation)].append(observation)
            if observation.period:
                self._by_period[observation.period].append(observation)

    def get(self, observation_id: str) -> Observation | None:
        return self._by_id.get(observation_id)

    def metrics(self) -> list[str]:
        return sorted(self._by_metric)

    def for_metric(self, metric: str) -> list[Observation]:
        return list(self._by_metric.get(metric.casefold(), []))

    def for_period(self, period: str) -> list[Observation]:
        return list(self._by_period.get(period, []))

    def query(
        self,
        *,
        metric: str | None = None,
        period: str | None = None,
        entity: str | None = None,
        dimensions: dict[str, str] | None = None,
        minimum_confidence: float = 0.0,
    ) -> list[Observation]:
        pool = self.for_metric(metric) if metric else self.observations
        return [
            observation
            for observation in pool
            if (period is None or observation.period == period)
            and (entity is None or observation.entity == entity)
            and observation.confidence >= minimum_confidence
            and all(observation.dimensions.get(key) == value for key, value in (dimensions or {}).items())
        ]

    @staticmethod
    def _metric_key(observation: Observation) -> str:
        return (observation.metric_canonical or observation.metric_original).casefold()

