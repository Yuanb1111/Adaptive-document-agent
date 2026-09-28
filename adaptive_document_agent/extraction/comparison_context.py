"""Restore literal table context without changing facts or inferring semantics.

Borderless reconstruction can join a standalone group heading to its first
numeric row. A matching named subtotal and the retained heading provide two
independent source anchors for that group. Table captions can also explicitly
name the subject of otherwise incomplete bucket labels such as "Within a year".
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from adaptive_document_agent.document_model.series import is_generic_metric_label
from adaptive_document_agent.models import Observation
from adaptive_document_agent.models.table import ExtractedTable


def _clean(value: str) -> str:
    return " ".join(value.split()).strip(" :;.")


def _contextual_label(label: str) -> bool:
    # A percentage suffix describes the column, not the missing parent of Others.
    base = label.split(":", 1)[0]
    return is_generic_metric_label(base) or bool(re.match(
        r"(?i)^(?:within|over|under|between|up to|less than|more than)\s+"
        r"(?:\d|one\b|two\b|three\b|four\b|five\b|six\b|seven\b|eight\b|nine\b|ten\b)",
        base,
    ))


def _caption_subject(table: ExtractedTable) -> str | None:
    """Copy an explicit caption subject, never use table/page IDs as meaning."""
    caption = " ".join(table.raw_header_lines)
    match = re.search(
        r"(?i)\b(?:following\s+)?table\s+(?:sets?\s+forth|shows?|presents?|provides?)\s+"
        r"(?:an?\s+)?(?:aging\s+analysis|breakdown|distribution|summary|details|analysis)\s+of\s+"
        r"(?:our\s+|the\s+)?(?P<subject>.+?)"
        r"(?=\s+(?:based\s+on|as\s+of|for\s+the|during)\b|[.;]|$)",
        caption,
    )
    if not match:
        return None
    subject = _clean(match.group("subject"))
    # A truncated caption without a boundary is not a reliable subject.
    if not subject or len(subject) > 120 or re.search(r"\b(?:19|20)\d{2}\b", subject):
        return None
    return subject


def table_comparison_contexts(table: ExtractedTable) -> dict[int, tuple[str | None, str | None]]:
    """Map source row indexes to an evidenced (parent, table subject)."""
    headings = {_clean(line).casefold() for line in table.raw_body_lines}
    labels = [_clean(row.cells[0] or "") if row.cells else "" for row in table.rows]
    parents: dict[int, str] = {}
    previous_total = -1
    for end, label in enumerate(labels):
        subtotal = re.fullmatch(r"(?i)sub\s*total\s+(?:of\s+)?(.+)", label)
        if not subtotal:
            continue
        parent = _clean(subtotal.group(1))
        folded = parent.casefold()
        if folded in headings:
            starts = [index for index in range(previous_total + 1, end)
                      if labels[index].casefold() == folded
                      or labels[index].casefold().startswith(folded + " ")]
            if len(starts) == 1:
                for index in range(starts[0], end):
                    if table.rows[index].alignment_status == "resolved":
                        parents[index] = parent
        previous_total = end

    subject = _caption_subject(table)
    return {
        index: (parents.get(index), subject if _contextual_label(label) else None)
        for index, label in enumerate(labels)
        if index in parents or (subject and _contextual_label(label))
    }


def with_comparison_context(
    observation: Observation,
    contexts: dict[int, tuple[str | None, str | None]],
) -> Observation:
    """Return an enriched copy; IDs, labels, numeric values and evidence stay intact."""
    parent, subject = contexts.get(observation.row_id, (None, None))
    dimensions = dict(observation.dimensions)
    updates: dict[str, object] = {}
    if parent and not observation.source_section:
        updates["parent_section"] = parent
        dimensions["section"] = parent
    if subject:
        dimensions["table_context"] = subject
    if dimensions != observation.dimensions:
        updates["dimensions"] = dimensions
    return observation.model_copy(update=updates) if updates else observation


def restore_comparison_context(
    observations: Iterable[Observation], tables: Iterable[ExtractedTable],
) -> list[Observation]:
    """Replay retained facts against their exact source cells, without re-extraction.

    Missing, ambiguous or changed source coordinates leave the observation alone.
    This permits older JSON exports to gain context while retaining all raw facts.
    """
    table_map = {table.table_id: table for table in tables}
    contexts = {key: table_comparison_contexts(table) for key, table in table_map.items()}
    result: list[Observation] = []
    for observation in observations:
        table = table_map.get(observation.effective_table_id or "")
        row, column = observation.row_id, observation.column_id
        if (table is not None and row is not None and column is not None
                and 0 <= row < len(table.rows) and 0 < column < len(table.rows[row].cells)
                and table.rows[row].alignment_status == "resolved"
                and table.rows[row].cells[column] == observation.raw_value
                and any(source.page == table.rows[row].page
                        and source.table_id == table.table_id
                        and source.row_label == table.rows[row].cells[0]
                        for source in observation.evidence)):
            observation = with_comparison_context(observation, contexts[table.table_id])
        result.append(observation)
    return result
