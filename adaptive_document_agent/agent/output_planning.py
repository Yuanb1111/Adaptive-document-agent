"""Independent report and presentation-question planning over shared evidence."""

from concurrent.futures import ThreadPoolExecutor
from adaptive_document_agent.models import PipelineResult, ReportPlan, PresentationTopicSelection
from adaptive_document_agent.services.llm import LLMGateway

from .report_planner import DynamicReportPlanner
from .presentation_topic_selector import PresentationTopicSelector


def plan_outputs(
    gateway: LLMGateway | None, result: PipelineResult,
) -> tuple[ReportPlan, PresentationTopicSelection | None, Exception | None]:
    """Keep local/stateful clients serial; never invoke UI callbacks in workers."""
    def report() -> ReportPlan:
        return DynamicReportPlanner(gateway).plan(result.profile, result.insights)

    def topics() -> tuple[PresentationTopicSelection | None, Exception | None]:
        if gateway is None:
            return None, None
        try:
            return PresentationTopicSelector(gateway).select(result), None
        except Exception as exc:
            return None, exc

    if gateway is not None and gateway.discovery_workers > 1:
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="output-planning") as pool:
            report_future = pool.submit(report)
            topic_future = pool.submit(topics)
            report_plan = report_future.result()
            selection, error = topic_future.result()
    else:
        report_plan = report()
        selection, error = topics()
    return report_plan, selection, error
