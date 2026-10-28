"""Resume unfinished checks only when the saved candidate and all context match."""
import json

from adaptive_document_agent.models.executive_brief import ExecutiveBrief
from adaptive_document_agent.services.executive_brief import validate_executive_brief
from .brief_review_checkpoint import context_key
from .brief_review_progress import report_brief_progress


def resume_brief_review(gateway, result, *, cancelled=None):
    from .brief_meaning_review import meaning_validator
    from .brief_item_repair import topic_coverage_errors
    from .brief_source_checks import record_uncited_checks
    environment = None
    seen = set()
    for warning in reversed(result.validation_warnings):
        if warning.code != 'executive_brief_review_checkpoint':
            continue
        try:
            record = json.loads(warning.message)
            key = record.get('context_key')
            if key in seen:
                continue
            seen.add(key)
            if not record.get('unavailable') or not record.get('source_context'):
                continue
            if environment is None:
                environment = context_key(None, None, result)
            if record.get('environment_key') != environment:
                continue
            candidate = ExecutiveBrief.model_validate(record['candidate'])
            context = record['source_context']
            if context_key(candidate, context, result) != record['context_key']:
                continue
            topics = [(t['title'], t['pages']) for t in context.get('selected_analysis_topics', [])]
            maximum = context.get('output_limits', {}).get('maximum_findings', 7)
            if (len(candidate.items) > maximum or validate_executive_brief(candidate, result)
                    or topic_coverage_errors(candidate, topics)):
                return None
        except (ValueError, KeyError, TypeError):
            continue
        report_brief_progress('resuming unfinished checks for the unchanged saved briefing')
        errors = meaning_validator(gateway, result=result, source_context=context,
                                   cancelled=cancelled)(candidate)
        if errors:
            # Genuine semantic rejection still needs normal authoring/repair.
            # This checkpoint never grants permission to drop or accept it.
            return None
        record_uncited_checks(result, candidate)
        return candidate
    return None
