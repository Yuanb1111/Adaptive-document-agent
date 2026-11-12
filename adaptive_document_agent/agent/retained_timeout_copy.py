"""Repair rejected saved page copy without discarding completed reporting work."""
import json
from typing import TYPE_CHECKING

from adaptive_document_agent.models import PipelineResult, ValidationIssue

if TYPE_CHECKING:
    from adaptive_document_agent.services.llm import LLMGateway
    from .retained_analysis import RetainedAnalysisSelection
    from .retained_page_sources import AuthoredPageErrors


def repair_timeout_copy(gateway: 'LLMGateway', result: PipelineResult,
                        selection: 'RetainedAnalysisSelection', context: dict,
                        errors: 'AuthoredPageErrors') -> None:
    from .retained_analysis import select_retained_analysis, compile_retained_analysis
    from .retained_page_sources import writer_context
    from .retained_selection_feedback import CODE, feedback_fingerprint

    _, aliases = writer_context(context)
    reverse = {oid: ref for ref, oid in aliases.items()}
    draft = selection.model_dump(mode='json', exclude_none=True)
    for decision in draft['decisions']:
        if decision.get('page'):
            decision['page']['companion_ids'] = [reverse.get(k, k) for k in decision['page']['companion_ids']]
    preserved = {d['insight_id']: d['page'] for d in draft['decisions']
                 if d['decision'] == 'include' and d['insight_id'] not in errors.by_insight}
    result.validation_warnings.append(ValidationIssue(code=CODE, stage='presentation', severity='info',
        message=json.dumps(dict(context_fingerprint=feedback_fingerprint(context),
            copy_review_ids=sorted(errors.by_insight), preserved_pages=preserved,
            rejected=dict(rejected_draft=draft, row_ids=aliases, diagnostic=str(errors),
                          reviewed_priorities=selection.ordered_insight_ids)), ensure_ascii=False)))
    select_retained_analysis(gateway, result)
    repaired = compile_retained_analysis(result)
    original = result.presentation_plan
    replacements = {s.id: s for s in repaired.slides if s.slide_type == 'analysis'}
    if set(replacements) != {s.id for s in original.slides if s.slide_type == 'analysis'}:
        raise ValueError('Timeout copy repair must preserve the saved analytical page identities')
    changed = {s.id for s in original.slides
               if s.slide_type == 'analysis' and set(s.insight_ids) & errors.by_insight.keys()}
    original.slides = [replacements[s.id] if s.id in changed else s for s in original.slides]
    themes = {t.id: t for t in repaired.themes}
    original.themes = [themes[t.id] if t.id in changed else t for t in original.themes]
