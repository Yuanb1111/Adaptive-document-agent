"""Use explicit source table row/column labels as a composition view."""

from collections import defaultdict
import re

SOURCE_ROW = "source_row"


def source_row_heading(title, chart, observations):
    """Repair only legacy mechanically prefixed source-column captions.

    Table context is retained as evidence metadata, not promoted to a chart
    subject. Authored headings and qualifications are never substring-stripped.
    """
    if not chart.composition_table_id or not observations:
        return title
    views = source_row_views(observations, chart.composition_table_id)
    contexts = {item.dimensions.get('table_context') for item in observations}
    columns = {item.metric_original for item in views}
    if len(contexts) != 1 or not next(iter(contexts)) or len(columns) != 1:
        return title
    context, column = next(iter(contexts)), next(iter(columns))
    base = f'{context} — {column}'
    normalize = lambda text: ' '.join(text.casefold().split())
    suffixes = ['', *(f' ({period})' for period in {item.period for item in observations} if period)]
    for suffix in suffixes:
        if normalize(title) == normalize(base + suffix):
            return f'{column} composition{suffix}'
    return title


def source_row_views(observations, table_id):
    """Project table labels for validation/rendering without editing raw facts."""
    views = []
    columns = set()
    for item in observations:
        labels = {(e.row_label, e.column_label) for e in item.evidence
                  if e.table_id == table_id and e.row_label and e.column_label}
        if len(labels) != 1:
            raise ValueError("Composition needs one explicit row and column in its source table.")
        row, column = next(iter(labels))
        normalize = lambda text: re.sub(r"\s+", "", text).casefold()
        if normalize(item.metric_original) != normalize(f"{row}: {column}"):
            raise ValueError("The source row/column labels do not identify the reported measure.")
        if item.category_dimensions or set(item.dimensions) - {"column_role", "period_basis", "table_context", "section"}:
            raise ValueError("Source-row composition cannot discard other category dimensions.")
        columns.add(column)
        views.append(item.model_copy(update={
            "metric_original": column, "metric_canonical": column,
            "source_table": table_id,
            "dimensions": {**item.dimensions, "table_context": table_id, SOURCE_ROW: row},
            "category_dimensions": {SOURCE_ROW: row},
        }))
    if len(columns) != 1:
        raise ValueError("Composition mixes source columns.")
    return views


def source_share_groups(observations):
    """Find reported share matrices within one table and comparable period basis."""
    groups = defaultdict(dict)
    for item in observations:
        if item.unit not in {"percent", "%", "percentage"}:
            continue
        for evidence in item.evidence:
            column = evidence.column_label or ""
            if not evidence.table_id or not re.search(r"(?i)(?:%|percent(?:age)?)\s*of\b|\bshare\b", column):
                continue
            key = (evidence.table_id, column, item.entity, item.source_section,
                   item.period_type, item.period_basis, item.ifrs_status, item.currency)
            groups[key][item.id] = item
    for key, members in groups.items():
        try:
            views = source_row_views(list(members.values()), key[0])
        except ValueError:
            continue
        yield key, views
