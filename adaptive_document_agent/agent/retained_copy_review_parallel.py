"""Independent owned copy verdicts share admission and retain full source context."""
import json
from concurrent.futures import ThreadPoolExecutor

from adaptive_document_agent.models import ValidationIssue


def review_owned_copy(context,selection,result,payload,review):
    from .retained_selection_coverage import RetainedSelectionCoverage,SelectionCoverageError
    from .retained_analysis import fingerprint
    targets=list(context['copy_review_ids'])
    def one(iid):
        current=result.model_copy(update={'validation_warnings':[]})
        failure=None
        try:
            review({**context,'copy_review_ids':[iid]},current)
        except Exception as exc:
            failure=exc
        return current.validation_warnings,failure
    completed=[]
    with ThreadPoolExecutor(max_workers=min(8,len(targets))) as pool:
        pending=[pool.submit(one,iid) for iid in targets]
        completed=[future.result() for future in pending]  # Drain all owners.
    issues=[];children=[];fatal=None
    for iid,(warnings,error) in zip(targets,completed):
        result.validation_warnings.extend(warnings)
        if error is not None and not isinstance(error,SelectionCoverageError):
            fatal=fatal or error
        if isinstance(error,SelectionCoverageError):
            if error.priority_ids or any(p.insight_id!=iid for p in error.page_issues):
                fatal=fatal or ValueError('Owned copy verdict cannot change another page or ranking')
            issues.extend(error.page_issues)
        audits=[json.loads(w.message) for w in warnings if w.code=='retained_selection_coverage']
        if not audits:
            fatal=fatal or ValueError('Owned source review did not produce its current audit')
        else:
            children.append(dict(insight_id=iid,input_fingerprint=audits[-1]['input_fingerprint']))
    if fatal is not None:
        raise fatal
    verdict=RetainedSelectionCoverage(accepted=not issues,page_issues=issues,
        reason='Independent owned source reviews passed.' if not issues else
               'Independent owned source reviews require the listed corrections.')
    audit=dict(input_fingerprint=fingerprint(payload),review=verdict.model_dump(mode='json'),
        copy_review_ids=targets,selected_ids=selection.ordered_insight_ids,
        owned_reviews=children,final_presentation_approval=False)
    result.validation_warnings.append(ValidationIssue(code='retained_selection_coverage',
        stage='presentation',severity='info',message=json.dumps(audit,ensure_ascii=False)))
    if issues:
        raise SelectionCoverageError('Owned copy corrections remain: '+ '; '.join(
            f'{p.insight_id}: {p.reason}' for p in issues),verdict)
