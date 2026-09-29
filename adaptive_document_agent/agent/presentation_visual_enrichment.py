"""Optional model choice of evidence-constrained analytical visual forms."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field

from adaptive_document_agent.models import PipelineResult, PresentationPlan
from adaptive_document_agent.models.presentation import HorizonItem, PresentationVisualBlock
from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator
from .prompting import load_prompt, untrusted_document_message


class VisualSuggestion(BaseModel):
    topic_id: str
    kind: Literal["waterfall", "matrix", "horizon"]
    observation_ids: list[str] = Field(default_factory=list, max_length=30)
    matrix_dimension: str = ""
    horizon_items: list[HorizonItem] = Field(default_factory=list, max_length=3)


class VisualSelection(BaseModel):
    suggestions: list[VisualSuggestion] = Field(default_factory=list, max_length=3)


def enrich_selected_plan(gateway, result: PipelineResult, plan: PresentationPlan) -> PresentationPlan:
    """Let the model choose relationships; accept only exact validated layouts.

    The existing chart plan is retained if the optional model call fails or an
    advanced view cannot be reconciled to the source. Each suggestion is checked
    independently so one weak proposal does not discard the presentation.
    """
    themes = {theme.id: theme for theme in plan.themes}
    candidates = {theme_id: [item for item in result.observations if item.id in theme.observation_ids]
                  for theme_id, theme in themes.items()}
    candidates = {key: records for key, records in candidates.items()
                  if 2 <= len(records) <= 30 and (
                      len(records) >= 4
                      or (len({item.metric_original for item in records}) >= 3
                          and len({item.effective_table_id for item in records}) == 1)
                      or (any(item.period_type in {"point_in_time", "balance_sheet_date"} for item in records)
                          and any(item.period_type not in {"point_in_time", "balance_sheet_date"}
                                  for item in records))
                  )}
    if not candidates:
        return plan
    # A future commitment may be described outside the tables selected for a
    # stock/flow topic. Include already discovered summary and insight pages;
    # retrieval does not assign them a temporal role or fabricate an amount.
    selected_pages = list(dict.fromkeys([
        *(page for theme_id in candidates for page in themes[theme_id].source_pages[:3]),
        *result.profile.document_summary_pages[:4],
        *(source.page for insight in sorted(result.insights, key=lambda item: -item.importance)[:8]
          for source in insight.evidence),
    ]))[:12]
    page_text = {page.page_number: page.text for page in result.document.pages}
    payload = {
        "topics": [
            {
                "topic_id": theme.id, "question": theme.question, "title": theme.title,
                "observations": [
                    {
                        "id": item.id, "metric": item.metric_original,
                        "value": item.value, "raw_value": item.raw_value,
                        "unit": item.unit, "raw_unit": item.raw_unit,
                        "currency": item.currency, "period": item.period,
                        "period_type": item.period_type, "period_basis": item.period_basis,
                        "entity": item.entity, "dimensions": item.dimensions,
                        "category_dimensions": item.category_dimensions,
                        "table_id": item.effective_table_id,
                        "source_pages": sorted({source.page for source in item.evidence}),
                        "source_quotes": [source.text[:180] for source in item.evidence if source.text][:2],
                    }
                    for item in candidates[theme.id]
                ],
            }
            for theme in plan.themes if theme.id in candidates
        ],
        "page_excerpts": [{"page": number, "text": page_text[number][:2500]}
                          for number in selected_pages if number in page_text],
    }
    try:
        selection = gateway.generate_structured([
            {"role": "system", "content": load_prompt("presentation_advanced_visuals.txt")},
            untrusted_document_message(json.dumps(payload, ensure_ascii=False)),
        ], VisualSelection, stage="presentation", allow_repair=False)
    except Exception:
        return plan
    current = plan
    used_topics: set[str] = set()
    for suggestion in selection.suggestions:
        theme = themes.get(suggestion.topic_id)
        if theme is None or suggestion.topic_id in used_topics:
            continue
        selected = set(suggestion.observation_ids)
        if not selected or not selected <= set(theme.observation_ids):
            continue
        block = PresentationVisualBlock(
            role=suggestion.kind, observation_ids=suggestion.observation_ids,
            matrix_dimension=suggestion.matrix_dimension,
            horizon_items=suggestion.horizon_items,
        )
        candidate = current.model_copy(deep=True)
        slide = next((item for item in candidate.slides
                      if item.slide_type == "analysis" and item.theme_id == theme.id), None)
        if slide is None:
            continue
        slide.chart_ids = []
        slide.visual_blocks = [block]
        slide.observation_ids = []
        source_by_id = {item.id: item for item in result.observations}
        slide.source_pages = sorted(
            {source.page for oid in selected for source in source_by_id[oid].evidence}
            | {page for item in suggestion.horizon_items for page in item.source_pages}
        )
        try:
            PresentationPlanValidator().validate(candidate, result)
        except ValueError:
            continue
        current = candidate
        used_topics.add(theme.id)
    return current
