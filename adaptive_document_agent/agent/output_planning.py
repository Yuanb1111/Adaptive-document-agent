"""Independent report and presentation-question planning over shared evidence."""

from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from typing import Callable
from adaptive_document_agent.models import PipelineResult, ReportPlan, PresentationTopicSelection
from adaptive_document_agent.services.llm import LLMGateway

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
        except Exception as exc:
            return None, exc

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
    return report_plan, selection, error
