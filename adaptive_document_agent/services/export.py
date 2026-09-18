"""User-facing and structured exports without losing raw values or evidence."""

import csv
import io

from pathlib import Path

from adaptive_document_agent.models import PipelineResult

from .pdf_export import build_report_pdf
from .pptx_export import build_presentation


def export_markdown(result: PipelineResult) -> bytes:
    return result.report_markdown.encode("utf-8")


def export_json(result: PipelineResult) -> bytes:
    return result.model_dump_json(indent=2).encode("utf-8")


def export_csv(result: PipelineResult) -> bytes:
    stream = io.StringIO(newline="")
    fields = ["id", "metric_original", "metric_canonical", "value", "raw_value", "period", "entity", "dimensions", "unit", "raw_unit", "unit_scale", "currency", "confidence", "pages"]
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    for item in result.observations:
        writer.writerow(
            {
                "id": item.id,
                "metric_original": item.metric_original,
                "metric_canonical": item.metric_canonical,
                "value": item.value,
                "raw_value": item.raw_value,
                "period": item.period,
                "entity": item.entity,
                "dimensions": item.model_dump_json(include={"dimensions"}),
                "unit": item.unit,
                "raw_unit": item.raw_unit,
                "unit_scale": item.unit_scale,
                "currency": item.currency,
                "confidence": item.confidence,
                "pages": ",".join(str(page) for page in sorted({source.page for source in item.evidence})),
            }
        )
    return stream.getvalue().encode("utf-8-sig")


def export_pptx(
    result: PipelineResult,
    template_path: str | Path | None = None,
    *,
    force: bool = False,
) -> bytes:
    from .qa_reporter import CriticalQAError, run_comprehensive_qa

    qa = run_comprehensive_qa(result)
    if not force and qa.has_critical_errors:
        reasons = "\n - ".join(e.message for e in qa.critical_errors)
        raise CriticalQAError(f"PowerPoint export blocked due to critical QA errors:\n - {reasons}")

    return build_presentation(result, template_path=template_path)


def export_pdf(result: PipelineResult) -> bytes:
    return build_report_pdf(result)
