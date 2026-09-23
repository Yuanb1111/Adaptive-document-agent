"""User-facing and structured exports without losing raw values or evidence."""

import csv
import io
import hashlib
from time import perf_counter

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
    renderer=None,
    visual_cache: dict | None = None,
    build_cache: dict | None = None,
    artwork: bytes | None = None,
    source_pdf: bytes | None = None,
) -> bytes:
    return export_pptx_with_report(result, template_path, force=force, renderer=renderer, visual_cache=visual_cache,
                                   build_cache=build_cache, artwork=artwork, source_pdf=source_pdf).payload


def export_pptx_with_report(
    result: PipelineResult,
    template_path: str | Path | None = None,
    *,
    force: bool = False,
    renderer=None,
    visual_cache: dict | None = None,
    build_cache: dict | None = None,
    artwork: bytes | None = None,
    source_pdf: bytes | None = None,
):
    """Financial QA, native generation, then strict local rendered validation.

    ``force`` retains its legacy financial-QA meaning; it never bypasses visual
    verification. The raw builder is internal, not a verified export API.
    """
    from .qa_reporter import CriticalQAError, run_comprehensive_qa
    from .presentation_visual_qa import verify_presentation
    from .presentation_artwork import validate_artwork
    artwork = validate_artwork(artwork)

    # Automatic QA repair loop:
    # Presentation Plan -> Claim Validation -> Repair contradictory wording -> Revalidate -> Export only if valid.
    started = perf_counter()
    qa = run_comprehensive_qa(result, auto_repair=True)
    qa_finished = perf_counter()
    if not force and qa.has_critical_errors:
        reasons = "\n - ".join(e.message for e in qa.critical_errors)
        raise CriticalQAError(f"PowerPoint export blocked due to critical QA errors:\n - {reasons}", financial_report=qa)

    try:
        # Cache only native generation. Financial QA above ALWAYS runs; rendered
        # QA below still checks its own content + renderer + policy fingerprint.
        template_digest = None
        cache_key = None
        if build_cache is not None:
            from .pptx_export import _resolve_template_path
            template_digest = hashlib.sha256(_resolve_template_path(template_path).read_bytes()).hexdigest()
            cache_key = _build_cache_key(result, template_digest, artwork, source_pdf)
        payload = build_cache.get(cache_key) if build_cache is not None else None
        build_cache_hit = isinstance(payload, bytes)
        if not build_cache_hit:
            payload = build_presentation(result, template_path=template_path, artwork=artwork, source_pdf=source_pdf)
        build_finished = perf_counter()
        verified = verify_presentation(payload, renderer=renderer, cache=visual_cache)
        if build_cache is not None:
            build_cache.clear()
            # QA/build may have repaired the plan in-place. Key the final state.
            build_cache[_build_cache_key(result, template_digest, artwork, source_pdf)] = payload
        verified.build_cache_hit = build_cache_hit
        verified.timings_ms = {
            "financial_qa": round((qa_finished - started) * 1000),
            "ppt_build": round((build_finished - qa_finished) * 1000),
            "rendered_qa": round((perf_counter() - build_finished) * 1000),
            "ppt_export_total": round((perf_counter() - started) * 1000),
        }
        return verified
    except CriticalQAError as exc:
        exc.financial_report = qa
        raise


def _build_cache_key(result: PipelineResult, template_digest: str, artwork: bytes | None = None,
                     source_pdf: bytes | None = None) -> tuple[str, str, str]:
    # Bump the version when generation rules change. All facts, source evidence,
    # narrative, charts, warnings and plan fields participate in invalidation.
    content = result.model_dump_json(exclude={"llm_usage", "timings_ms"}).encode()
    from adaptive_document_agent.utils.pipeline_version import PIPELINE_VERSION
    image_digest = hashlib.sha256(source_pdf).digest() if source_pdf is not None else b""
    return (f"ppt-build-v3:{PIPELINE_VERSION}", template_digest,
            hashlib.sha256(content + b"\0" + (artwork or b"") + b"\0" + image_digest).hexdigest())


def export_pdf(result: PipelineResult) -> bytes:
    return build_report_pdf(result)
