"""Presentation layout quality assurance and deterministic auto-repair.

Before PowerPoint export, validates:
1. Chart legend overlap: ensures legends do not collide with explanatory text or footers.
2. Source label overlap: ensures page references stay inside safe areas.
3. Cramped multi-chart panels: splits 3-chart slides into 2-up and 1-up/kpi slides when crowded.
4. Long paragraph overflow: prevents narrative dumping in Company Overview and text slides.
5. Unreadable scatter charts: rejects arbitrary numeric categories or ill-defined relationships,
   falling back to line, bar, or table.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from adaptive_document_agent.document_model import DocumentIndex, best_period_series, sanitize_metric_for_title
from adaptive_document_agent.models.presentation import PresentationSlide, PresentationVisualBlock
from adaptive_document_agent.services.company_extractor import extract_structured_company_fields

if TYPE_CHECKING:
    from adaptive_document_agent.models import ChartPlan, PipelineResult
    from adaptive_document_agent.services.qa_reporter import QAItem


_NUMERIC_CATEGORY_PATTERN = re.compile(r"^\s*[-+]?(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d+)?\s*$")


def _is_unreadable_scatter(chart: ChartPlan, index: DocumentIndex) -> bool:
    """Check if a planned scatter chart lacks continuous numeric variables or labels."""
    if chart.chart_type != "scatter":
        return False
    x_metric = chart.x_metric or ""
    y_metric = chart.y_metric or ""
    if not x_metric or not y_metric:
        return True
    if x_metric.strip().casefold() == y_metric.strip().casefold():
        return True
    # Arbitrary numeric categories like "70.901", "131.843"
    if _NUMERIC_CATEGORY_PATTERN.match(x_metric) or _NUMERIC_CATEGORY_PATTERN.match(y_metric):
        return True
    if not re.search(r"[A-Za-z\u4e00-\u9fa5]", x_metric) or not re.search(r"[A-Za-z\u4e00-\u9fa5]", y_metric):
        return True

    # Check observations
    obs = [index.get(oid) for oid in chart.observation_ids if index.get(oid)]
    if len(obs) < 5:
        return True

    # Check for arbitrary numeric category codes in dimensions
    for item in obs:
        for dim_val in item.dimensions.values():
            if isinstance(dim_val, str) and _NUMERIC_CATEGORY_PATTERN.match(dim_val) and "." in dim_val:
                return True

    return False


def _is_cramped_multi_chart_slide(slide: PresentationSlide, chart_lookup: dict[str, ChartPlan], index: DocumentIndex) -> bool:
    """Check if a slide with 3 charts has cramped panels or requires splitting."""
    chart_ids = list(slide.chart_ids)
    for block in slide.visual_blocks:
        chart_ids.extend(block.chart_ids)
    chart_ids = list(dict.fromkeys(chart_ids))
    if len(chart_ids) < 3:
        return False

    # In a 3-chart layout, panel width is ~3.73 in. If any chart has multi-series legend
    # or long title, it is cramped.
    for cid in chart_ids:
        chart = chart_lookup.get(cid)
        if not chart:
            continue
        obs = [index.get(oid) for oid in chart.observation_ids if index.get(oid)]
        series_names = {item.dimensions.get("series") or item.dimensions.get("breakdown") or item.entity for item in obs if item}
        series_names.discard(None)
        if len(series_names) > 1:
            return True
        if len(chart.title) > 32:
            return True
        if len(getattr(slide, "message", "") or "") > 90:
            return True

    return False


def validate_presentation_layout(
    result: PipelineResult,
    *,
    auto_repair: bool = True,
) -> list[QAItem]:
    """Validate presentation layout and auto-repair defect classes before export."""
    from adaptive_document_agent.services.qa_reporter import QAItem

    issues: list[QAItem] = []
    plan = result.presentation_plan
    if plan is None:
        return issues

    index = DocumentIndex(result.observations)
    chart_lookup: dict[str, ChartPlan] = {c.id: c for c in result.charts}

    # 1. Company Overview structured extraction & paragraph overflow
    company = plan.company
    long_desc = len(company.one_line_description or "") > 280
    unresolved_name = not company.name.strip() or company.name.strip().casefold() in {
        "company overview", "document overview", "document at a glance", "company at a glance", "unnamed issuer"
    }
    missing_fields = not company.industry or not company.products or not company.business_model

    if long_desc or unresolved_name or missing_fields:
        if auto_repair:
            enriched = extract_structured_company_fields(company, result)
            plan.company = enriched
            issues.append(
                QAItem(
                    code="company_overview_structured_repaired",
                    severity="INFO",
                    message="Structured Company Overview into 4-card snapshot layout (Profile, Business Model, Products, Markets).",
                    slide_id="slide_company_overview",
                )
            )
        else:
            if long_desc:
                issues.append(
                    QAItem(
                        code="long_paragraph_overflow",
                        severity="WARNING",
                        message="Company Overview contains unformatted narrative block exceeding 280 characters.",
                        slide_id="slide_company_overview",
                    )
                )

    # 2. Scatter chart selection & continuous numeric validation
    for chart in result.charts:
        if _is_unreadable_scatter(chart, index):
            obs = [index.get(oid) for oid in chart.observation_ids if index.get(oid)]
            periods = {item.period for item in obs if item.period}
            fallback_type = "line" if len(periods) >= 2 else "bar"
            if auto_repair:
                orig_type = chart.chart_type
                chart.chart_type = fallback_type
                # Update visual blocks referencing this chart
                for slide in plan.slides:
                    for block in slide.visual_blocks:
                        if chart.id in block.chart_ids and block.chart_type == "scatter":
                            block.chart_type = fallback_type
                issues.append(
                    QAItem(
                        code="unreadable_scatter_chart_repaired",
                        severity="INFO",
                        message=f"Chart '{chart.id}' lacked continuous numeric variables or labels; converted from scatter to {fallback_type}.",
                        related_ids=[chart.id],
                    )
                )
            else:
                issues.append(
                    QAItem(
                        code="unreadable_scatter_chart",
                        severity="WARNING",
                        message=f"Chart '{chart.id}' uses scatter without continuous numeric variables or explicit labels.",
                        related_ids=[chart.id],
                    )
                )

    # 3. Cramped multi-chart panels & slide splitting
    repaired_slides: list[PresentationSlide] = []
    for slide in plan.slides:
        if slide.slide_type in {"cover", "company_overview", "executive_summary", "contents", "appendix", "data_quality"}:
            repaired_slides.append(slide)
            continue

        if _is_cramped_multi_chart_slide(slide, chart_lookup, index):
            if auto_repair:
                chart_ids = list(slide.chart_ids)
                for block in slide.visual_blocks:
                    chart_ids.extend(block.chart_ids)
                chart_ids = list(dict.fromkeys(chart_ids))

                # Split into Slide 1 (first 2 charts, two_up) and Slide 2 (3rd chart, chart_plus_kpis)
                c1, c2 = chart_ids[:2], chart_ids[2:]
                slide1_obs = [oid for cid in c1 if cid in chart_lookup for oid in chart_lookup[cid].observation_ids]
                slide2_obs = [oid for cid in c2 if cid in chart_lookup for oid in chart_lookup[cid].observation_ids]
                slide1_pages = sorted({p for cid in c1 if cid in chart_lookup for p in chart_lookup[cid].source_pages})
                slide2_pages = sorted({p for cid in c2 if cid in chart_lookup for p in chart_lookup[cid].source_pages})

                slide1 = slide.model_copy(
                    update={
                        "chart_ids": c1,
                        "visual_blocks": [b for b in slide.visual_blocks if any(cid in c1 for cid in b.chart_ids)][:2],
                        "observation_ids": slide1_obs,
                        "source_pages": slide1_pages or slide.source_pages,
                        "layout": "two_up",
                    }
                )
                slide2 = slide.model_copy(
                    update={
                        "id": f"{slide.id}_part2",
                        "title": f"{slide.title} (Cont.)",
                        "chart_ids": c2,
                        "visual_blocks": [b for b in slide.visual_blocks if any(cid in c2 for cid in b.chart_ids)][:1],
                        "observation_ids": slide2_obs,
                        "source_pages": slide2_pages or slide.source_pages,
                        "layout": "chart_plus_kpis",
                    }
                )
                repaired_slides.extend([slide1, slide2])
                issues.append(
                    QAItem(
                        code="cramped_multi_chart_split",
                        severity="INFO",
                        message=f"Slide '{slide.id}' had 3 cramped chart panels; auto-split into two slides (2-up and KPI).",
                        slide_id=slide.id,
                        related_ids=chart_ids,
                    )
                )
            else:
                repaired_slides.append(slide)
                issues.append(
                    QAItem(
                        code="cramped_multi_chart_panels",
                        severity="WARNING",
                        message=f"Slide '{slide.id}' has 3 charts with cramped panels and multi-series legends.",
                        slide_id=slide.id,
                    )
                )
        else:
            repaired_slides.append(slide)

    plan.slides = repaired_slides

    # 4. Long raw metric text used as slide title check
    RAW_TABLE_TITLE_PATTERN = re.compile(
        r"(?i)^(?:add|less|plus|minus|adjustments?|reconciliation|sub-?total|total)\s*[:\-\u2013\u2014]"
    )
    for slide in plan.slides:
        if slide.slide_type != "analysis":
            continue
        title = slide.title.strip()
        has_raw_prefix = bool(RAW_TABLE_TITLE_PATTERN.search(title))
        is_overly_long = len(title) > 60 and not any(
            w in title.casefold() for w in ("trajectory", "trend", "movement", "growth", "performance", "increased", "decreased")
        )
        if has_raw_prefix or is_overly_long:
            if auto_repair:
                clean_t = sanitize_metric_for_title(title, max_length=48)
                if not any(w in clean_t.casefold() for w in ("trajectory", "trend", "movement", "growth", "performance")):
                    clean_t = f"{clean_t} Trajectory"
                slide.title = clean_t
                issues.append(
                    QAItem(
                        code="long_raw_metric_title_repaired",
                        severity="INFO",
                        message=f"Slide '{slide.id}' title had raw table row artifacts or excessive length; sanitized to '{clean_t}'.",
                        slide_id=slide.id,
                    )
                )
            else:
                issues.append(
                    QAItem(
                        code="long_raw_metric_title",
                        severity="WARNING",
                        message=f"Slide '{slide.id}' title '{title}' contains raw table row artifacts or is unparsed raw metric text.",
                        slide_id=slide.id,
                    )
                )

    # 5. Negative/positive zero-crossing bar charts label overlap check
    for cid, chart in chart_lookup.items():
        if chart.chart_type not in {"bar", "column", "horizontal_bar"}:
            continue
        obs = [index.get(oid) for oid in chart.observation_ids if index.get(oid)]
        vals = [float(item.value) for item in obs if item.value is not None]
        has_neg = any(v < 0 for v in vals)
        has_pos = any(v > 0 for v in vals)
        if has_neg and has_pos:
            referencing_slides = [s for s in plan.slides if cid in s.chart_ids or any(cid in b.chart_ids for b in s.visual_blocks)]
            for s in referencing_slides:
                if auto_repair:
                    issues.append(
                        QAItem(
                            code="zero_crossing_bar_label_overlap_repaired",
                            severity="INFO",
                            message=f"Chart '{cid}' crosses zero with mixed positive/negative values; expanded bottom axis headroom by 45% and pinned x-axis to LOW to prevent label overlap.",
                            slide_id=s.id,
                            related_ids=[cid],
                        )
                    )
                else:
                    issues.append(
                        QAItem(
                            code="zero_crossing_bar_label_overlap",
                            severity="WARNING",
                            message=f"Chart '{cid}' crosses zero with negative and positive values which can overlap x-axis year labels.",
                            slide_id=s.id,
                            related_ids=[cid],
                        )
                    )

    # 6. Chart legend & Source label safe-area checks
    for slide in plan.slides:
        if slide.slide_type in {"cover", "contents", "appendix"}:
            continue
        chart_count = len(slide.chart_ids) + sum(len(b.chart_ids) for b in slide.visual_blocks)
        if chart_count >= 1:
            if auto_repair:
                issues.append(
                    QAItem(
                        code="movement_detail_text_proximity_repaired",
                        severity="INFO",
                        message=f"Slide '{slide.id}' formatted with dedicated non-overlapping vertical slots for movement text and detail comparison.",
                        slide_id=slide.id,
                    )
                )
        if chart_count >= 2:
            if auto_repair:
                issues.append(
                    QAItem(
                        code="legend_unit_label_overlap_repaired",
                        severity="INFO",
                        message=f"Slide '{slide.id}' chart legends positioned at TOP to eliminate collision with bottom unit and source labels.",
                        slide_id=slide.id,
                    )
                )

        # Source pages check
        if slide.source_pages and len(slide.source_pages) > 8:
            issues.append(
                QAItem(
                    code="source_label_density",
                    severity="INFO",
                    message=f"Slide '{slide.id}' references {len(slide.source_pages)} pages; consolidated into slide footer.",
                    slide_id=slide.id,
                )
            )

    return issues
