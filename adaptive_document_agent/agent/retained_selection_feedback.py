"""Reuse a rejected draft as feedback, never as a selection or source approval."""
import json

from adaptive_document_agent.models import ValidationIssue

CODE = 'retained_selection_retry_feedback'


def feedback_fingerprint(context):
    from .retained_analysis import fingerprint
    # A regenerated provisional outline may change its title/order even when
    # every source, requirement, finding and calculation is identical. It is
    # not an approval boundary for reusing draft feedback; final selection and
    # publication review still bind the full current context including outline.
    return fingerprint({k: v for k, v in context.items() if k != 'report_outline'})


def can_retry_source_review(previous):
    """One bounded correction of source-authored pages before catalog fallback."""
    from .retained_analysis import selected_record, selection_context, fingerprint
    if (previous.failed_stage != 'presentation_coverage'
            or previous.failure_details.get('component') != 'PresentationCoverage'):
        return False
    try:
        if any(w.code == CODE and json.loads(w.message).get('source_review')
               for w in previous.validation_warnings):
            return False
        latest = next((w for w in reversed(previous.validation_warnings)
                       if w.code == 'presentation_retained_analysis_review'), None)
        if latest is None:
            return False
        from .retained_analysis_review import review_context
        if json.loads(latest.message).get('fingerprint') != fingerprint(review_context(previous)):
            return False
        record = selected_record(previous)
        return bool(record and record.get('source_authoring')
                    and record['input_fingerprint'] == fingerprint(selection_context(previous)))
    except (ValueError, KeyError, TypeError):
        return False


def retain_selection_feedback(previous):
    if can_retry_source_review(previous):
        from .retained_analysis import selected_record, selection_context, fingerprint
        from .retained_page_sources import writer_context
        context = selection_context(previous)
        _, aliases = writer_context(context)
        reverse = {oid: alias for alias, oid in aliases.items()}
        selection = json.loads(json.dumps(selected_record(previous)['selection']))
        for decision in selection['decisions']:
            if decision.get('page'):
                decision['page']['companion_ids'] = [reverse.get(k, k) for k in decision['page']['companion_ids']]
        latest = next(w for w in reversed(previous.validation_warnings)
                      if w.code == 'presentation_retained_analysis_review')
        accepted_slides = {v['slide_id'] for v in json.loads(latest.message)['review']['verdicts'] if v['accepted']}
        accepted_findings = {iid for slide in previous.presentation_plan.slides if slide.id in accepted_slides
                             for iid in slide.insight_ids}
        preserved = {d['insight_id']: d['page'] for d in selection['decisions']
                     if d['insight_id'] in accepted_findings and d.get('page')}
        record = dict(context_fingerprint=feedback_fingerprint(context), source_review=True,
            preserved_pages=preserved,
            rejected=dict(rejected_draft=selection, row_ids=aliases,
                          diagnostic=previous.failure_details.get('message', 'Original-page review failed')))
        return ValidationIssue(code=CODE, stage='presentation', severity='info',
                               message=json.dumps(record, ensure_ascii=False))
    if (previous.failed_stage != 'presentation_selection'
            or previous.failure_details.get('component') != 'RetainedAnalysisSelection'):
        return None
    issue = next((w for w in reversed(previous.validation_warnings)
                  if w.code == 'retained_page_draft_rejected'), None)
    if issue is None:
        return None
    from .retained_analysis import selection_context, fingerprint
    try:
        draft = json.loads(issue.message)
        context = selection_context(previous, source_authoring=True)
        record = dict(context_fingerprint=feedback_fingerprint(context), rejected=draft)
    except (ValueError, KeyError, TypeError):
        return None
    return ValidationIssue(code=CODE, stage='presentation', severity='info',
                           message=json.dumps(record, ensure_ascii=False))


def selection_retry_feedback(result, context):
    from .retained_analysis import fingerprint, RetainedAnalysisSelection, _validate_selection
    from .retained_page_sources import validate_authored_pages
    issue = next((w for w in reversed(result.validation_warnings) if w.code == CODE), None)
    if issue is None:
        return None
    try:
        record = json.loads(issue.message)
        if record['context_fingerprint'] != feedback_fingerprint(context):
            return None
        rejected = record['rejected']
        selection = RetainedAnalysisSelection.model_validate(rejected['rejected_draft'])
        aliases = rejected['row_ids']
        for decision in selection.decisions:
            if decision.page:
                decision.page.companion_ids = [aliases.get(k, k) for k in decision.page.companion_ids]
        _validate_selection(selection, context)
    except (ValueError, KeyError, TypeError):
        return None
    fresh_errors = []
    try:
        validate_authored_pages(selection, context, result)
    except ValueError as exc:
        fresh_errors.append(str(exc))
    return dict(rejected_draft=rejected['rejected_draft'], previous_errors=rejected['diagnostic'],
                current_binding_errors=fresh_errors, source_review=record.get('source_review', False),
                preserved_pages=record.get('preserved_pages', {}),
                final_approval=False)
