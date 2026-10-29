"""Short request-local addresses for large catalogs; source content stays literal."""
from copy import deepcopy
import json

from adaptive_document_agent.models import ValidationIssue
from .coverage_review_context import compact_context, encode

REFERENCE_INSTRUCTIONS = (
    'The catalog uses request-local series IDs. Copy the exact ID beside the selected metric '
    'into series_ids and omission.series_id. All notes and period views use those same IDs. '
    'Do not reconstruct persistent hashes, invent an ID or interpret an ID as evidence. '
    'Python restores the exact retained identities before every source and meaning check.')


def reference_input(payload):
    """Replace only typed address fields, never labels, source text or raw values."""
    wire = deepcopy(payload)
    position = wire['series_columns'].index('id')
    ids = [row[position] for row in wire['all_extracted_series']]
    if len(ids) != len(set(ids)):
        raise ValueError('Topic catalog contains duplicate retained identities')
    reserved, references, number = set(ids), {}, 0
    for identifier in ids:
        while f's{number}' in reserved:
            number += 1
        references[f's{number}'] = identifier
        number += 1
    reverse = {original: short for short, original in references.items()}
    for row in wire['all_extracted_series']:
        row[position] = reverse[row[position]]
    for field in ('ratio_definitions', 'source_row_qualifications'):
        for row in wire.get(field, []):
            row['series_id'] = reverse[row['series_id']]
    for view in wire.get('same_source_row_period_views', []):
        for row in view['same_source_row']:
            row['series_id'] = reverse[row['series_id']]
    return wire, references


def selection_request(payload):
    original = encode(compact_context(payload), factor_cells=True)
    if len(original) < 64_000:
        return original, {}
    wire, references = reference_input(payload)
    encoded = encode(compact_context(wire), factor_cells=True)
    if len(encoded) + len(REFERENCE_INSTRUCTIONS) >= len(original):
        return original, {}
    return encoded, references


def restore_selection(selection, references, result):
    if not references:
        return
    # Unknown IDs remain invalid for the existing scoped validation/repair.
    # No fuzzy suffix matching, dropped topic or new analytical decision here.
    for topic in selection.topics:
        topic.series_ids = [references.get(sid, sid) for sid in topic.series_ids]
    for omission in selection.omissions:
        omission.series_id = references.get(omission.series_id, omission.series_id)
    for decision in getattr(selection, 'coverage_decisions', []):
        decision.series_id = references.get(decision.series_id, decision.series_id)
    result.validation_warnings.append(ValidationIssue(code='presentation_topic_reference_map',
        stage='presentation', severity='info', message=json.dumps(dict(
            contract='topic-selection-addresses-v215', references=references), ensure_ascii=False)))
