"""Check the final localized native deck before reporting pipeline completion."""
import json
from concurrent.futures import CancelledError

from adaptive_document_agent.models import ValidationIssue
from adaptive_document_agent.services.llm.exceptions import PrivacyViolationError


def check_final_presentation_layout(result):
    """No authoring or semantic selection; preserve retryable layout diagnostics.

    Native composition already tries lossless layout alternatives and complete
    continuations. Overflow must remain a reporting failure, never an implicit
    permission to remove meaning, shrink fonts or relax the user's limit.
    """
    if result.presentation_plan is None:
        return True
    record = {'status': 'pending', 'phase': 'after_localization', 'introduction_pages': []}
    try:
        from .presentation_budget_refinement import measure
        from adaptive_document_agent.services.summary_export import _PREFIX, verify_summary_export
        from adaptive_document_agent.services.slide_budgets import require_exported_budgets
        deck, counts = measure(result)
        record['physical_counts'] = counts
        mapping = {}
        for number, slide in enumerate(deck.slides, 1):
            for shape in slide.shapes:
                properties = shape.element.xpath('.//p:cNvPr')
                marker = properties[0].get('descr', '') if properties else ''
                if marker.startswith(_PREFIX):
                    binding = json.loads(marker[len(_PREFIX):])
                    mapping.setdefault(binding['page_id'], set()).add(number)
        record['introduction_pages'] = [dict(page_id=page.id, title=page.title,
            slide_numbers=sorted(mapping.get(page.id, set())), placement=page.placement)
            for page in result.presentation_plan.company.summary_pages]
        verify_summary_export(deck, result)
        require_exported_budgets(deck, result)
        record['status'] = 'passed'
    except (CancelledError, PrivacyViolationError):
        raise
    except Exception as exc:
        record.update(status='failed', error_type=type(exc).__name__, error=str(exc))
        result.pipeline_state = 'partial'
        result.retry_from = 'reporting'
        result.failed_stage = 'final_presentation_layout'
        result.failure_details = dict(component='FinalPresentationLayout',
            error_type=type(exc).__name__, message=str(exc))
    result.validation_warnings.append(ValidationIssue(
        code='final_presentation_layout', stage='presentation',
        severity='info' if record['status'] == 'passed' else 'warning',
        message=json.dumps(record, ensure_ascii=False)))
    return record['status'] == 'passed'
