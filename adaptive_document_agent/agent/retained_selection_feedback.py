"""Reuse a rejected draft as feedback, never as a selection or source approval."""
import json

from adaptive_document_agent.models import PipelineResult, ValidationIssue

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
    from .retained_analysis import selected_record, selection_context, fingerprint, selection_input_matches
    if (previous.failed_stage != 'presentation_coverage'
            or previous.failure_details.get('component') != 'PresentationCoverage'):
        return False
    try:
        latest = next((w for w in reversed(previous.validation_warnings)
                       if w.code == 'presentation_retained_analysis_review'), None)
        if latest is None:
            return False
        # Each newly completed independent review may supply new objections.
        # A consumed verdict cannot buy another repair without that fresh gate.
        latest_index = max(i for i, w in enumerate(previous.validation_warnings)
                           if w.code == 'presentation_retained_analysis_review')
        if any(w.code == CODE and json.loads(w.message).get('source_review')
               for w in previous.validation_warnings[latest_index + 1:]):
            return False
        from .retained_analysis_review import review_context
        if json.loads(latest.message).get('fingerprint') != fingerprint(review_context(previous)):
            return False
        record = selected_record(previous)
        return bool(record and record.get('source_authoring')
                    and selection_input_matches(record, selection_context(previous), previous))
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
        review_record = json.loads(latest.message)
        review = review_record.get('effective_review', review_record['review'])
        accepted_slides = {v['slide_id'] for v in review['verdicts'] if v['accepted']}
        accepted_findings = {iid for slide in previous.presentation_plan.slides if slide.id in accepted_slides
                             for iid in slide.insight_ids}
        preserved = {d['insight_id']: d['page'] for d in selection['decisions']
                     if d['insight_id'] in accepted_findings and d.get('page')}
        record = dict(context_fingerprint=feedback_fingerprint(context), source_review=True,
            preserved_pages=preserved,
            rejected=dict(rejected_draft=selection, row_ids=aliases,
                          diagnostic=previous.failure_details.get('message', 'Original-page review failed')))
        if review['omissions_accepted']:
            record['rejected']['reviewed_priorities'] = selection['ordered_insight_ids']
            reasons = {v['slide_id']: v['reason'] for v in review['verdicts'] if not v['accepted']}
            record['earlier_page_issues'] = {iid: [reasons[slide.id]]
                for slide in previous.presentation_plan.slides if slide.id in reasons
                for iid in slide.insight_ids}
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
        # Older checkpoints stored the structured priority verdict separately.
        # Carry it forward as correction feedback, never as publication approval.
        if 'reviewed_priorities' not in draft:
            coverage = next((w for w in reversed(previous.validation_warnings)
                             if w.code == 'retained_selection_coverage'), None)
            audit = json.loads(coverage.message) if coverage else {}
            review = (audit.get('effective_review', audit.get('review', {}))
                      if not audit.get('copy_review_ids') else {})
            priorities = review.get('prioritized_insight_ids', [])
            included = set(draft['rejected_draft']['ordered_insight_ids'])
            missing = set(review.get('missing_insight_ids', []))
            if priorities and missing and set(priorities) - included == missing:
                draft['reviewed_priorities'] = priorities
        included = set(draft['rejected_draft']['ordered_insight_ids'])
        earlier_page_issues = {}
        for warning in previous.validation_warnings:
            if warning.code != 'retained_selection_coverage':
                continue
            try:
                audit = json.loads(warning.message)
            except (ValueError, TypeError):
                continue
            if not isinstance(audit, dict):
                continue
            review = audit.get('effective_review', audit.get('review', {}))
            for issue in review.get('page_issues', []):
                if issue['insight_id'] in included:
                    reasons = earlier_page_issues.setdefault(issue['insight_id'], [])
                    if issue['reason'] not in reasons:
                        reasons.append(issue['reason'])
        record = dict(context_fingerprint=feedback_fingerprint(context), rejected=draft,
                      earlier_page_issues=earlier_page_issues)
    except (ValueError, KeyError, TypeError):
        return None
    return ValidationIssue(code=CODE, stage='presentation', severity='info',
                           message=json.dumps(record, ensure_ascii=False))


def selection_retry_feedback(result, context):
    from .retained_analysis import RetainedAnalysisSelection, _validate_selection, repair_omission_ids
    from .retained_page_sources import rebind_context_evidence, validate_authored_pages
    issue = next((w for w in reversed(result.validation_warnings) if w.code == CODE), None)
    if issue is None:
        return None
    try:
        record = json.loads(issue.message)
        if record['context_fingerprint'] != feedback_fingerprint(context):
            return None
        rejected = record['rejected']
        draft = rejected['rejected_draft']
        selection = RetainedAnalysisSelection.model_validate(draft)
        if repair_omission_ids(selection, context):
            draft = selection.model_dump(mode='json', exclude_none=True)
        aliases = rejected['row_ids']
        for decision in selection.decisions:
            if decision.page:
                decision.page.companion_ids = [aliases.get(k, k) for k in decision.page.companion_ids]
        _validate_selection(selection, context)
        priorities = rejected.get('reviewed_priorities', [])
        eligible = {f['insight']['id'] for f in context['findings'] if f['selectable']}
        if (len(priorities) != len(set(priorities)) or set(priorities) - eligible
                or len(priorities) > context.get('selection_capacity', 8)):
            return None
    except (ValueError, KeyError, TypeError):
        return None
    fresh_errors = []
    if priorities and set(selection.ordered_insight_ids) != set(priorities):
        fresh_errors.append(f'The corrected selection must retain the independently chosen priorities: {priorities}')
    try:
        rebind_context_evidence(selection, context, result)
        validate_authored_pages(selection, context, result)
    except ValueError as exc:
        fresh_errors.append(str(exc))
    return dict(rejected_draft=draft, previous_errors=rejected['diagnostic'],
                current_binding_errors=fresh_errors, source_review=record.get('source_review', False),
                selection_unchanged=not priorities or set(selection.ordered_insight_ids) == set(priorities),
                reviewed_priorities=priorities,
                earlier_page_issues=record.get('earlier_page_issues', {}),
                preserved_pages=record.get('preserved_pages', {}),
                copy_review_ids=record.get('copy_review_ids', []),
                final_approval=False)


def selection_output_truncated(previous):
    """Recognize incomplete generation, never a partially approved selection."""
    if (previous.pipeline_state != 'partial' or previous.retry_from != 'reporting'
            or previous.presentation_topics is not None
            or previous.failed_stage != 'presentation_selection'
            or previous.failure_details.get('error_type') != 'LLMStructuredOutputError'):
        return False
    for warning in reversed(previous.validation_warnings):
        if warning.code not in {'retained_selection_format_repair', 'retained_selection_output_capacity'}:
            continue
        try:
            audit = json.loads(warning.message)
            if not isinstance(audit, dict):
                return False
            return (audit.get('status') == 'truncated' or
                    bool(audit.get('attempts')) and audit['attempts'][-1]['status'] == 'truncated')
        except (ValueError, KeyError, TypeError):
            return False
    return False


def restore_rejected_findings(previous: PipelineResult | None, current: PipelineResult) -> bool:
    """Restore unchanged findings and completed selection across downstream failures."""
    intro_retry = previous is not None and (previous.failed_stage or '').startswith('introduction')
    if (previous is None or not intro_retry and (previous.failed_stage, previous.failure_details.get('component')) not in {
                ('presentation_selection', 'RetainedAnalysisSelection'),
                ('presentation_planning', 'RetainedAnalysisPlan'),
                ('presentation_coverage', 'PresentationCoverage')}
            or not previous.insights or previous.report_plan is None
            or any(getattr(previous, key) != getattr(current, key) for key in
                   ('document', 'profile', 'observations', 'analysis_plan', 'analysis_results'))):
        return False
    from .retained_analysis import SELECTION_CODE, fingerprint, selected_record, selection_context, selection_input_matches
    candidate = current.model_copy(update={
        'insights': [i.model_copy(deep=True) for i in previous.insights],
        'report_plan': previous.report_plan.model_copy(deep=True)})
    if previous.failed_stage == 'presentation_planning' or intro_retry:
        record = selected_record(previous)
        context = selection_context(candidate, source_authoring=bool((record or {}).get('source_authoring')))
        if not record or not selection_input_matches(record, context, candidate):
            return False
        current.validation_warnings.extend(w.model_copy(deep=True) for w in previous.validation_warnings
            if w.code in {SELECTION_CODE, 'retained_selection_coverage'})
    elif selection_output_truncated(previous):
        current.validation_warnings.append(ValidationIssue(code='retained_selection_upstream_resume',
            stage='presentation', severity='info', message='Reused source-identical provisional findings '
            'and outline after truncated selection output. Selection, numeric binding, omission and '
            'independent source reviews remain pending. No partial response was restored.'))
    elif selection_retry_feedback(candidate, selection_context(candidate, source_authoring=True)) is None:
        return False
    current.insights, current.report_plan = candidate.insights, candidate.report_plan
    return True
