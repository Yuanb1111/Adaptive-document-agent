"""Privacy-safe, model-agnostic run records for lightweight evaluation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from adaptive_document_agent.models import PipelineResult


class ExportOutcome(BaseModel):
    format: str
    success: bool
    failure_reason: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    cache_hit: bool | None = None


class EvaluationRunRecord(BaseModel):
    recorded_at: str
    code_version: str
    pipeline_version: str | None
    file_id: str
    dataset_role: Literal["fix_sample", "holdout"]
    run_mode: Literal["first_run", "cached_run"]
    model_settings: list[dict[str, Any]] = Field(default_factory=list)
    cache_hits: dict[str, int] = Field(default_factory=dict)
    stage_timings_ms: dict[str, int] = Field(default_factory=dict)
    total_duration_ms: int | None = Field(default=None, ge=0)
    exports: list[ExportOutcome] = Field(default_factory=list)
    real_file_verified: bool = False
    notes: list[str] = Field(default_factory=list)


_SAFE_MODEL_FIELDS = {"stage", "operation", "provider", "model", "resolved_model", "status",
                      "thinking_mode", "reasoning_policy"}


def build_evaluation_record(
    result: PipelineResult,
    *,
    code_version: str,
    dataset_role: Literal["fix_sample", "holdout"],
    run_mode: Literal["first_run", "cached_run"],
    exports: list[ExportOutcome] | None = None,
    real_file_verified: bool = False,
    notes: list[str] | None = None,
) -> EvaluationRunRecord:
    """Build a record without filenames, document text, prompts, or credentials."""
    cache_hits: dict[str, int] = {}
    settings: list[dict[str, Any]] = []
    seen = set()
    for usage in result.llm_usage:
        if usage.get("cache_hit"):
            stage = str(usage.get("stage", "unknown"))
            cache_hits[stage] = cache_hits.get(stage, 0) + 1
        safe = {key: usage[key] for key in _SAFE_MODEL_FIELDS if usage.get(key) is not None}
        marker = repr(sorted(safe.items()))
        if safe and marker not in seen:
            settings.append(safe)
            seen.add(marker)
    timings = {**result.timings_ms, **result.stage_details_ms, **result.export_timings_ms}
    return EvaluationRunRecord(
        recorded_at=datetime.now(timezone.utc).isoformat(),
        code_version=code_version,
        pipeline_version=result.pipeline_version,
        file_id=result.document.sha256,
        dataset_role=dataset_role,
        run_mode=run_mode,
        model_settings=settings,
        cache_hits=cache_hits,
        stage_timings_ms=timings,
        total_duration_ms=result.pipeline_total_ms,
        exports=exports or [],
        real_file_verified=real_file_verified,
        notes=notes or [],
    )
