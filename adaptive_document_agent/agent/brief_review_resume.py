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
            checks = record.get('checked', {})
            complete_rejection = (isinstance(checks, dict) and not record.get('pending')
                and not record.get('unavailable') and any(checks.values()))
            completed = record.get('semantic_approval') is True and not record.get('pending') and not record.get('unavailable')
            if not (record.get('unavailable') or complete_rejection or completed) or not record.get('source_context'):
                continue
            if environment is None:
                environment = context_key(None, None, result)
            if record.get('environment_key') != environment:
                continue
            if complete_rejection:
                from .brief_retry_feedback import current_feedback
                feedback = current_feedback(result)
                if feedback and (feedback.get('rejected_strategy') == 'unchanged-rejected-brief-text-correction'
                                 or feedback.get('source_correction_required')):
                    # A text-only edit cannot add new quoted endpoints. On an
                    # explicit retry let the source-bound item repair pick
                    # evidence, then require independent review of that draft.
                    return None
            candidate = ExecutiveBrief.model_validate(record['candidate'])
            if completed and checks != {str(i): [] for i in range(len(candidate.items))}:
                continue
            if complete_rejection and (set(checks) != {str(i) for i in range(len(candidate.items))}
                    or not all(isinstance(reasons, list) and all(isinstance(reason, str) for reason in reasons)
                               for reasons in checks.values())):
                continue
            context = record['source_context']
            if context_key(candidate, context, result) != record['context_key']:
                continue
            topics = [(t['title'], t['pages']) for t in context.get('selected_analysis_topics', [])]
            maximum = context.get('output_limits', {}).get('maximum_findings', 7)
            if (not candidate.title.strip() or len(candidate.items) > maximum or validate_executive_brief(candidate, result)
                    or topic_coverage_errors(candidate, topics)):
                return None
        except (ValueError, KeyError, TypeError):
            continue
        report_brief_progress('rechecking the latest completed briefing' if completed
                              else 'repairing the unchanged rejected briefing' if complete_rejection
                              else 'resuming unfinished checks for the unchanged saved briefing')
        validator = meaning_validator(gateway, result=result, source_context=context, cancelled=cancelled)
        errors = validator(candidate)
        if errors:
            if complete_rejection or record.get('unavailable'):
                # Finishing an interrupted review can produce a real rejection.
                # It is the same source-validated candidate: repair only those
                # freshly failed items instead of replacing the whole brief.
                from .brief_rejected_resume import correct_saved_rejection
                corrected = correct_saved_rejection(gateway, result, candidate, context, topics, errors,
                    validator, cancelled=cancelled)
                record_uncited_checks(result, corrected)
                return corrected
            # Genuine semantic rejection still needs normal authoring/repair.
            # This checkpoint never grants permission to drop or accept it.
            return None
        record_uncited_checks(result, candidate)
        return candidate
    return None
