"""Spend an existing final compression on missing selected assertions, never approval."""
from copy import deepcopy


def missing_meanings_only(errors):
    return bool(errors) and all(error.startswith('Authored coverage is missing required meaning: ')
                                for error in errors)


def restore_selected_meanings(gateway, original, rejected, catalog, review, record, schema,
                             *, original_feedback, original_physical_groups, repair_limit, cancelled=None):
    """Keep the original identity/fact baseline and all current selected meanings."""
    from .summary_layout_feedback import layout_feedback
    from .summary_layout_patch import compress_pages
    record['rejected_compression'] = dict(pages=rejected.model_dump(mode='json')['pages'],
        errors=list(record['errors']), status='source_invalid', semantic_approval=False)
    record['layout_feedback'] = deepcopy(original_feedback) if original_feedback is not None else layout_feedback(
        original, None, review, catalog)
    record['physical_groups'] = deepcopy(original_physical_groups)
    record['compression_round'] = repair_limit
    record['compression_round_limit'] = repair_limit
    record['compression_recovery'] = dict(preservation_baseline='original_authored_identity_and_fact_ids',
        original_meaning_completeness_assumed=False, rejected_copy_is_diagnostic_only=True,
        consumes_existing_final_compression=True, semantic_approval=False)
    instruction = (
        'This is the FINAL bounded physical compression correction, using the remaining existing round. '
        'current_pages is the ORIGINAL authored copy and protects its identity and original fact IDs; '
        'it is not assumed complete for selected meaning. rejected_compression is a failed diagnostic, '
        'never a new preservation baseline. Restore EVERY already-selected required meaning missing '
        'from either authored copy, using its complete exact owning source passage. Restore actual '
        'audience assertions and all necessary numbers, periods, bases, attribution, uncertainty and '
        'conditions, not merely reference metadata. Do not add independent unselected assertions. '
        'Synthesize the complete selected union within the measured physical allocation, retaining '
        'the supported opening and ALL original fact IDs. Return complete pages and explicit '
        'part_id/meaning_index mappings to paragraphs actually expressing each meaning. Python '
        'binds exact current paragraph text and does not infer a mapping or semantic coverage. '
        'If the complete selected meaning cannot fit readably, retain it so the final gate fails '
        'transparently. Every binding, physical cap and fresh independent per-meaning source review '
        'must still pass; this recovery grants no acceptance.')
    return compress_pages(gateway, original, catalog, record, instruction, schema,
                          cancelled=cancelled, audience_selected=True)
