"""Independent report and presentation-question planning over shared evidence."""

from concurrent.futures import CancelledError, ThreadPoolExecutor, wait, FIRST_COMPLETED
from typing import Callable
from adaptive_document_agent.models import PipelineResult, ReportPlan, PresentationTopicSelection
from adaptive_document_agent.services.llm import LLMGateway
from adaptive_document_agent.services.llm.exceptions import PrivacyViolationError

from .report_planner import DynamicReportPlanner
from .presentation_topic_selector import PresentationTopicSelector


def plan_outputs(
    gateway: LLMGateway | None, result: PipelineResult, *, timings: dict[str, int] | None = None,
    progress: Callable[[str], None] | None = None,
) -> tuple[ReportPlan, PresentationTopicSelection | None, Exception | None]:
    """Keep local/stateful clients serial; never invoke UI callbacks in workers."""
    from adaptive_document_agent.utils.timing import record_timing
    timings = timings if timings is not None else {}
    notify = progress or (lambda stage: None)
    def report() -> ReportPlan:
        with record_timing(timings, "report_outline"):
            return DynamicReportPlanner(gateway).plan(result.profile, result.insights)

    def topics() -> tuple[PresentationTopicSelection | None, Exception | None]:
        if gateway is None:
            return None, None
        try:
            with record_timing(timings, "topic_selection"):
                return PresentationTopicSelector(gateway).select(result), None
        except (PrivacyViolationError, CancelledError):
            raise
        except Exception as exc:
            return None, exc

    from .retained_analysis import can_reuse, select_retained_analysis, selected_record, selection_input_matches, selection_context
    if gateway is not None and can_reuse(gateway, result):
        record = selected_record(result)
        if record and selection_input_matches(record, selection_context(result), result):
            from .retained_analysis import RetainedAnalysisSelection, _validate_selection
            from .retained_page_sources import validate_authored_pages
            context = selection_context(result)
            selection = RetainedAnalysisSelection.model_validate(record['selection'])
            _validate_selection(selection, context)
            if record.get('source_authoring'):
                validate_authored_pages(selection, context, result)
            notify('Rechecking the retained report selection before presentation compilation')
            return result.report_plan, None, None
        notify('Planning report from validated analysis findings')
        report_plan = report()
        result.report_plan = report_plan
        try:
            with record_timing(timings, 'retained_analysis_selection'):
                select_retained_analysis(gateway, result)
        except (PrivacyViolationError, CancelledError):
            raise
        except Exception as exc:
            # A failed bounded selection cannot fall through to a second paid
            # full-catalogue workflow or silently approve a fallback deck.
            result.pipeline_state, result.retry_from = 'partial', 'reporting'
            result.failed_stage = 'presentation_selection'
            result.failure_details = dict(component='RetainedAnalysisSelection',
                error_type=type(exc).__name__, message=str(exc))
            return report_plan, None, exc
        return report_plan, None, None

    if gateway is not None and gateway.discovery_workers > 1:
        notify('Planning report outline and selecting presentation questions')
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="output-planning") as pool:
            report_future = pool.submit(report)
            topic_future = pool.submit(topics)
            pending = {report_future, topic_future}
            while pending:
                _, pending = wait(pending, return_when=FIRST_COMPLETED)
                if pending:
                    notify('Planning report outline' if report_future in pending
                           else 'Selecting presentation questions before chart generation')
            report_plan = report_future.result()
            selection, error = topic_future.result()
    else:
        notify('Planning report outline')
        report_plan = report()
        notify('Selecting presentation questions before chart generation')
        selection, error = topics()
    from .topic_evidence_review import CoverageTopicReviewError
    if isinstance(error, CoverageTopicReviewError):
        result.pipeline_state, result.retry_from = 'partial', 'reporting'
        result.failed_stage = 'presentation_coverage'
        result.failure_details = dict(component='TopicEvidenceReview', error_type=type(error).__name__,
                                      message=str(error))
    else:
        latest = next((issue for issue in reversed(getattr(result, 'validation_warnings', ())) if issue.code in
            {'presentation_topic_coverage_unresolved', 'presentation_topic_coverage_review'}), None)
        if latest is not None and latest.code == 'presentation_topic_coverage_unresolved':
            result.pipeline_state, result.retry_from = 'partial', 'reporting'
            result.failed_stage = 'presentation_coverage'
            result.failure_details = dict(component='PresentationCoverage', retry_strategy='full_catalog',
                message='The final catalog coverage decision is incomplete. Retry the selection before briefing.')
    return report_plan, selection, error
