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


def readable_chart_heading(title: str, *, composition: bool = False) -> str:
    """Keep chart captions tied to their measure without pipeline boilerplate."""
    from .language_qa import clean_display_copy

    label = clean_display_copy(title)
    label = re.sub(r"%\s*of\s*", "% of ", label, flags=re.I)
    label = re.sub(r"(?i)\s*(?:[-–—]\s*)?reported values(?=\s*(?:\(|$))", "", label).strip()
    if composition and re.fullmatch(r"(?i)(?:(?:%\s*of\s*total|share of total)(?:\s+composition)?|composition)", label):
        return "Category share of total"
    return label or "Reported measure"


def _composition_scope(chart, observations, totals):
    """Resolve only explicit component labels from a validated plotted matrix."""
    from .composition_data import composition_data
    from .source_row_composition import source_row_views

    data = composition_data(chart, observations, totals)
    views = source_row_views(observations, chart.composition_table_id) if chart.composition_table_id else observations
    dimension = chart.series_dimension or chart.x_dimension
    aliases = {}
    for original, view in zip(observations, views):
        category = {**view.dimensions, **view.category_dimensions}[dimension]
        for label in (category, original.metric_original, display_metric_name(original), qualified_metric_name(original)):
            aliases.setdefault(_composition_label_key(label), set()).add(category)
    # A shared metric such as "Responses" identifies the whole measure, not
    # one component. Only labels that identify exactly one part are mechanical.
    components = {label: next(iter(categories)) for label, categories in aliases.items()
                  if label and len(categories) == 1}
    heading = chart.title
    if not heading.strip() or _composition_inventory(heading, components, data.categories, single=True):
        measures = {view.metric_original for view in views}
        heading = next(iter(measures)) + " composition" if len(measures) == 1 else "Category composition"
    return readable_chart_heading(heading, composition=True), components, data.categories


def _composition_label_key(text: str) -> str:
    """Match display whitespace without making a semantic approximation."""
    return " ".join(re.sub(r"%\s*of\s*", "% of ", text, flags=re.I).casefold().split())


def _composition_inventory(text, components, categories, *, single=False):
    """An exact component or complete label list is not an analytical claim."""
    value = _composition_label_key(text)
    if single and value in components:
        return True
    if not value or not components:
        return False
    # Match full known labels first: category names may themselves contain
    # commas or "and", which must not be split into imagined components.
    labels = sorted(components, key=len, reverse=True)
    pattern = "(?:" + "|".join(re.escape(label) for label in labels) + ")"
    separator = r"\s*(?:,\s*(?:and\s+)?|;|\band\b|&)\s*"
    if not re.fullmatch(pattern + "(?:" + separator + pattern + ")+", value):
        return False
    found = {components[match.group()] for match in re.finditer(pattern, value)}
    return found == set(categories)


def composition_heading(title, chart, observations, totals=()):
    """Scope mechanical component captions to the complete composition.

    Authored takeaways are preserved verbatim. No denominator or subject is
    inferred from surrounding table prose; the chart's own title is preferred.
    """
    heading, components, categories = _composition_scope(chart, observations, totals)
    return heading if _composition_inventory(title, components, categories, single=True) else title


def composition_message(message, chart, observations, totals=()):
    """Let the chart legend carry an exact repeated component inventory."""
    _, components, categories = _composition_scope(chart, observations, totals)
    if not _composition_inventory(message, components, categories):
        return message
    question = chart.question.strip()
    return "" if _composition_inventory(question, components, categories, single=True) else question
