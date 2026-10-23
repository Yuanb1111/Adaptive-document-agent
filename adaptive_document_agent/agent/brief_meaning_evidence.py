"""Reapply the same source, arithmetic and assurance gates to a review response."""
import json

from adaptive_document_agent.services.source_quotes import normalize_quote


def review_evidence_errors(response, *, brief, pending, catalogs, result=None, binding_errors=None):
    from .brief_meaning_review import comparison_errors
    from .brief_audit_scope import audit_status_errors
    binding_errors = binding_errors or {}
    audit = {'response': response.model_dump(mode='json'), 'source_catalogs': catalogs,
             'source_audit_scopes': {row['index']: row['source_audit_scope'] for row in pending}, 'errors': {}}
    errors = {}
    for verdict in response.items:
        item = brief.items[verdict.index]
        failed = [*binding_errors.get(verdict.index, []), *([] if verdict.accepted else [verdict.reason])]
        failed.extend(audit_status_errors(item, result, inventory=next(
            row['source_audit_scope'] for row in pending if row['index'] == verdict.index)))
        if verdict.numeric_comparison and not verdict.comparisons:
            failed.append('Every asserted numeric change needs source-bound comparison endpoints')
        for comparison in verdict.comparisons:
            updates = {}
            for field in ('start', 'end', 'delta'):
                ref = getattr(comparison, field + '_ref')
                if ref:
                    context = catalogs[verdict.index].get(ref)
                    if context is None:
                        failed.append('Comparison reference is outside its item evidence')
                    else:
                        supplied = getattr(comparison, field + '_context')
                        if supplied and normalize_quote(supplied) != normalize_quote(context):
                            failed.append('Comparison reference contradicts its supplied context')
                        updates[field + '_context'] = context
            comparison = comparison.model_copy(update=updates)
            source_percentages = None
            if comparison.measure_basis == 'source_percentage' and result is not None:
                from adaptive_document_agent.services.executive_brief import _quoted_table_percentages, _quantities
                from adaptive_document_agent.services.brief_table_evidence import quoted_table_context
                source_percentages = (_quoted_table_percentages(item, result)
                    | quoted_table_context(item, result).percentages
                    | {v for q in item.evidence for c, v, u in _quantities(q.text)
                       if not c and u in {'%', 'percent'}})
            failed.extend(comparison_errors(comparison, item, pages=(
                {p.page_number: p.text for p in result.document.pages} if result is not None else None),
                source_percentages=source_percentages))
        if failed:
            errors[verdict.index] = failed
            audit['errors'][str(verdict.index)] = failed
    if result is not None:
        from adaptive_document_agent.models import ValidationIssue
        result.validation_warnings.append(ValidationIssue(code='executive_brief_meaning_audit',
            stage='report', severity='info', message=json.dumps(audit, ensure_ascii=False)))
    return errors
