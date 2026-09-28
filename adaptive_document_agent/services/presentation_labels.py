"""Keep source-defined measure scope visible without changing observations."""

import re

from adaptive_document_agent.document_model import display_metric_name
from adaptive_document_agent.models import Observation


_METADATA = {"table_context", "section", "period_basis", "column_role"}


def _contains(text: str, value: str) -> bool:
    normalize = lambda s: " ".join(re.findall(r"[^\W_]+", s.casefold()))
    return f" {normalize(value)} " in f" {normalize(text)} "


def scope_dimensions(observation: Observation) -> dict[str, str]:
    """Category dimensions are audience context; table/column metadata is not."""
    return {k: str(v).strip() for k, v in
            {**observation.dimensions, **observation.category_dimensions}.items()
            if k not in _METADATA and str(v).strip()}


def qualify_heading(title: str, observations: list[Observation]) -> str:
    """Append only qualifiers explicitly shared by every displayed observation."""
    if not observations:
        return title
    common = scope_dimensions(observations[0])
    for observation in observations[1:]:
        dimensions = scope_dimensions(observation)
        common = {k: v for k, v in common.items()
                  if dimensions.get(k, "").casefold() == v.casefold()}
    missing = list(dict.fromkeys(v for v in common.values() if not _contains(title, v)))
    return f"{title} ({', '.join(missing)})" if missing else title


def qualified_metric_name(observation: Observation) -> str:
    return qualify_heading(display_metric_name(observation), [observation])
