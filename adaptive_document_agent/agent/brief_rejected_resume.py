"""One explicit-retry correction of an unchanged, fully reviewed rejected brief."""
from .brief_item_repair import _audit
from .brief_semantic_repair import correct_new_meaning_errors
from adaptive_document_agent.services.llm.exceptions import LLMResponseError


def source_matched_candidate(result, context, excerpts, topics):
    """Recover draft text only when the complete current evidence is identical.

    Report titles and accumulated diagnostics may change a review environment.
    This path reuses no verdict or locked item: the normal writer must classify
    EVERY candidate again against its current context before applying a patch.
    """
    import json
    from adaptive_document_agent.models.executive_brief import ExecutiveBrief
    from adaptive_document_agent.services.executive_brief import validate_executive_brief
    from .brief_item_repair import topic_coverage_errors
    best, rejected = None, []
    for warning in reversed(result.validation_warnings):
        if warning.code != 'executive_brief_review_checkpoint':
            continue
        try:
            record = json.loads(warning.message)
            old = record['source_context']
            checks = record['checked']
            if record.get('pending') or record.get('unavailable'):
                continue
            # Optional extraction/transport aids can be rebuilt by a code
            # correction. They grant no authority. All raw source blocks,
            # topic/focus/supplementary scope and output limits must match;
            # current table/value checks below and a fresh review still run.
            hints = {'previous_rejected_brief', 'source_native_quantity_options', 'source_table_guide',
                     'companion_context_pages', 'source_excerpt_scope'}
            old = dict(old)
            old_limits, current_limits = old.get('output_limits', {}), context.get('output_limits', {})
            previous_quotes, current_quotes = old_limits.get('quotes_per_item'), current_limits.get('quotes_per_item')
            if (isinstance(previous_quotes, int) and isinstance(current_quotes, int)
                    and current_quotes >= previous_quotes):
                old['output_limits'] = {**old_limits, 'quotes_per_item': current_quotes}
            canonical = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
            if (canonical({k: v for k, v in old.items() if k not in hints})
                    != canonical({k: v for k, v in context.items() if k not in hints})):
                rejected.append(dict(kind='source_context_changed', fields=[key for key in set(old) | set(context)
                    if key not in hints and canonical(old.get(key)) != canonical(context.get(key))]))
                continue
            candidate = ExecutiveBrief.model_validate(record['candidate'])
            if (set(checks) != {str(i) for i in range(len(candidate.items))}
                    or not all(isinstance(v, list) and all(isinstance(s, str) for s in v) for v in checks.values())
                    or not candidate.title.strip()
                    or len(candidate.items) > context.get('output_limits', {}).get('maximum_findings', 7)
                    or validate_executive_brief(candidate, result, excerpts=excerpts)
                    or topic_coverage_errors(candidate, topics)):
                continue
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
        # Preserve the model's complete proposed findings for current review.
        # A rejected smaller selection must not erase its missing counterpoints.
        # At equal size prefer the latest candidate. No verdict is reused.
        if best is None or len(candidate.items) > len(best.items):
            best = candidate
    if best is None and rejected:
        from adaptive_document_agent.models import ValidationIssue
        result.validation_warnings.append(ValidationIssue(code='executive_brief_candidate_resume_skipped',
            stage='report', severity='info', message=json.dumps(rejected[:4], ensure_ascii=False)))
    return best


def correct_saved_rejection(gateway, result, candidate, context, topics, errors, validator, *, cancelled=None):
    """Keep every item and source binding; repair only freshly rejected text.

    The caller already matched document, data, topics, plan and full review
    context. Old failures are questions, not facts; the current independent
    reviewer has rechecked them. No source or semantic approval is inherited.
    """
    audit = dict(original=candidate.model_dump(mode='json'), original_response=None,
        locked_indices=[i for i in range(len(candidate.items)) if i not in errors],
        initial_errors={f'item_{i}': ['Meaning review: ' + error for error in reasons]
                        for i, reasons in errors.items()},
        patch=None, patch_response=None, repair_errors=[], discarded_indices=[],
        retry_strategy='unchanged-rejected-brief-text-correction')
    excerpts = {page.page_number: page.text for page in result.document.pages}
    try:
        corrected = correct_new_meaning_errors(gateway, candidate, result=result, excerpts=excerpts,
            topics=topics, source_context=context, evidence_catalog=context.get('evidence_blocks'),
            semantic_validator=validator, audit=audit, cancelled=cancelled, editable_indices=set(errors))
    except (ValueError, LLMResponseError) as exc:
        audit['repair_errors'] = [str(exc)]
        _audit(result, audit, 'rejected')
        raise
    if corrected is None:
        detail = audit.get('post_source_meaning_correction', {}).get('errors_after')
        audit['repair_errors'] = detail or [error for reasons in errors.values() for error in reasons]
        _audit(result, audit, 'rejected')
        raise ValueError('Saved executive briefing correction failed: ' + '; '.join(audit['repair_errors']))
    _audit(result, audit, 'repaired')
    return corrected
