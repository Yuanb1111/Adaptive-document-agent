"""Verify assurance objections against the exact bound source column."""
from typing import Literal

from pydantic import BaseModel, ConfigDict

from .brief_audit_scope import _STATUS, _located_header, geometric_column_statuses


ASSURANCE_REVIEW_RULES = (
    'verified_column_assurance rechecks the positioned original header against the exact table cell. '
    'Use its observation ID, source table and column together. Unknown here means this column is '
    'unmarked. A neighboring column, shared interim heading, or flattened text cannot supply a '
    'qualifier. For a finding rejected solely for audit status, use assurance_changes with the exact '
    'bound observation ID and the status the source requires (unknown to remove a label). Leave '
    'assurance_changes empty for a rejection with any other issue so that independent evidence '
    'and completeness objections remain actionable. Do not treat these bindings as approval. ')


class AssuranceChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    observation_id: str
    status: Literal['audited', 'unaudited', 'unknown']


def verified_column_assurance(result, observation_ids):
    """Match the literal header and original row/column before resolving an objection."""
    tables = {(p.page_number, t.table_id): (p, t) for p in result.document.pages for t in p.tables}
    checked_tables = {}
    bindings = {}
    for observation in result.observations:
        if observation.id not in observation_ids or observation.column_id is None or observation.row_id is None:
            continue
        column, row = observation.column_id, observation.row_id
        for evidence in observation.evidence:
            key = (evidence.page, evidence.table_id)
            if key not in tables or evidence.table_id != observation.effective_table_id:
                continue
            page, table = tables[key]
            if not (0 < column < len(table.column_periods) and 0 <= row < len(table.rows)):
                continue
            source_row = table.rows[row]
            if (source_row.page != page.page_number or source_row.alignment_status != 'resolved'
                    or column >= len(source_row.cells) or source_row.cells[column] != observation.raw_value
                    or table.column_periods[column] != observation.period):
                continue
            if key not in checked_tables:
                labels = [label for raw in table.raw_header_lines
                          if (label := _located_header(raw, page.text)) and _STATUS.search(label)]
                # A single literal marker with a unique geometric owner is enough
                # to distinguish marked and neighboring unmarked columns. Leave
                # ambiguous or multiple-marker cases to the independent reviewer.
                statuses = (geometric_column_statuses(page, table, labels)
                            if len(labels) == 1 and len(_STATUS.findall(labels[0])) == 1 else [])
                checked_tables[key] = statuses if any(s in {'audited', 'unaudited'} for s in statuses) else []
            statuses = checked_tables[key]
            if column <= len(statuses) and statuses[column - 1] == observation.audited_status:
                bindings[observation.id] = dict(page=page.page_number, table_id=table.table_id,
                    column=column, period=observation.period, metric=observation.metric_original,
                    status=observation.audited_status)
                break
    return bindings


def contradicted_assurance(changes, observation_ids, bindings):
    """Only discount a pure assurance objection contradicted in every cited cell."""
    return bool(changes) and all(
        change.observation_id in observation_ids
        and change.observation_id in bindings
        and bindings[change.observation_id]['status'] != change.status
        for change in changes
    )
