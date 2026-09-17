"""Editable, presentation-ready PowerPoint export for analysis results based on the FOURIER template."""

from __future__ import annotations

from collections import defaultdict
import io
import os
from pathlib import Path
import re
from typing import Any, Iterable

from pptx.util import Inches, Pt

from adaptive_document_agent.document_model import (
    DocumentIndex,
    display_metric_name,
    is_meaningful_metric,
    metric_key,
    paired_observations,
    period_sort_key,
)
from adaptive_document_agent.document_model.metric_semantic_classifier import (
    classify_metric,
    format_metric_change,
    format_metric_display_value,
    sanitize_metric_label,
)
from adaptive_document_agent.document_model.period_semantic_validator import (
    classify_period,
    format_period_label,
)
from adaptive_document_agent.models import ChartPlan, Observation, PipelineResult, PresentationSlide
from adaptive_document_agent.services.ppt_preflight import PresentationPreflight
from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
BUNDLED_TEMPLATE_PATH = PACKAGE_ROOT / "templates" / "FOURIER Light Version Template EN_251217.pptx"
LOCAL_DESKTOP_TEMPLATE_PATH = Path(r"C:\Users\yuanb\Desktop\FOURIER Light Version Template EN_251217.pptx")
DEFAULT_TEMPLATE_PATH = str(BUNDLED_TEMPLATE_PATH if BUNDLED_TEMPLATE_PATH.exists() else LOCAL_DESKTOP_TEMPLATE_PATH)

# Fourier Light Theme Palette (theme1.xml)
FOURIER_PURPLE = "7A24FD"        # Primary accent 1
FOURIER_LIGHT_PURPLE = "AB74FF"  # Accent 2
FOURIER_TECH_BLUE = "0086D1"     # Accent 3
FOURIER_AMBER = "F4B923"         # Accent 4
FOURIER_DEEP_BLUE = "2E3CED"     # Accent 5
FOURIER_CYAN = "20ECF1"          # Accent 6

FOURIER_DARK = "1A1A1A"          # Main text
FOURIER_MUTED = "575757"         # Subtitle, metadata, secondary text
FOURIER_BG_CARD = "F8F9FA"       # Card / panel background
FOURIER_BORDER = "E7E6E6"        # Subtle border / rule
WHITE = "FFFFFF"

# Aliases for backwards compatibility with tests / helpers
NAVY = FOURIER_DARK
MIDNIGHT = FOURIER_DARK
INK = FOURIER_DARK
MUTED = FOURIER_MUTED
BLUE = FOURIER_TECH_BLUE
TEAL = FOURIER_CYAN
VIOLET = FOURIER_PURPLE
AMBER = FOURIER_AMBER
CORAL = FOURIER_LIGHT_PURPLE
IVORY = FOURIER_BG_CARD
STONE = FOURIER_BORDER
FONT = "Arial"
TITLE_FONT = "Arial"

CHART_PALETTE = (
    FOURIER_PURPLE,
    FOURIER_TECH_BLUE,
    FOURIER_AMBER,
    FOURIER_CYAN,
    FOURIER_LIGHT_PURPLE,
    FOURIER_DEEP_BLUE,
)


def _resolve_template_path(template_path: str | Path | None = None) -> Path:
    if template_path:
        path = Path(template_path).resolve()
        if not path.exists():
            raise FileNotFoundError(
                f"Required PowerPoint template file not found at '{path}'. "
                "Please ensure the FOURIER template exists or set PPTX_TEMPLATE_PATH."
            )
        if not path.is_file():
            raise ValueError(f"Specified PowerPoint template path is not a file: '{path}'")
        return path

    env_target = os.environ.get("PPTX_TEMPLATE_PATH")
    if env_target:
        path = Path(env_target).resolve()
        if not path.exists():
            raise FileNotFoundError(
                f"Required PowerPoint template file not found at '{path}'. "
                "Please ensure the FOURIER template exists or set PPTX_TEMPLATE_PATH."
            )
        if not path.is_file():
            raise ValueError(f"Specified PowerPoint template path is not a file: '{path}'")
        return path

    if BUNDLED_TEMPLATE_PATH.exists() and BUNDLED_TEMPLATE_PATH.is_file():
        return BUNDLED_TEMPLATE_PATH

    if LOCAL_DESKTOP_TEMPLATE_PATH.exists() and LOCAL_DESKTOP_TEMPLATE_PATH.is_file():
        return LOCAL_DESKTOP_TEMPLATE_PATH

    raise FileNotFoundError(
        f"Required PowerPoint template file not found at bundled path '{BUNDLED_TEMPLATE_PATH}' "
        f"or desktop path '{LOCAL_DESKTOP_TEMPLATE_PATH}'. "
        "Please ensure the FOURIER template exists or set PPTX_TEMPLATE_PATH."
    )


def build_presentation(result: PipelineResult, template_path: str | Path | None = None) -> bytes:
    """Return an editable, presentation-ready PowerPoint based on the FOURIER Light Version Template."""
    try:
        from pptx import Presentation
    except ImportError as exc:  # pragma: no cover - deployment configuration failure
        raise RuntimeError("PowerPoint export requires python-pptx.") from exc

    resolved_path = _resolve_template_path(template_path)
    try:
        presentation = Presentation(str(resolved_path))
    except Exception as exc:
        raise ValueError(f"Failed to load PowerPoint template at '{resolved_path}': {exc}") from exc

    # Remove template sample slides while retaining master, layouts, and theme
    slide_ids = list(presentation.slides._sldIdLst)
    for sld_id in slide_ids:
        rId = sld_id.rId
        presentation.part.drop_rel(rId)
        del presentation.slides._sldIdLst[presentation.slides._sldIdLst.index(sld_id)]

    if result.presentation_plan:
        PresentationPlanValidator().validate(result.presentation_plan, result)
        _build_planned_presentation(presentation, result)
    else:
        _build_legacy_presentation(presentation, result)
    _number_slides(presentation)

    # Pre-export preflight check and sanitization
    preflight = PresentationPreflight(presentation)
    preflight.validate_and_sanitize()

    stream = io.BytesIO()
    presentation.save(stream)
    return stream.getvalue()


def _content_zone(slide: Any) -> tuple[float, float]:
    """Return (content_top, content_height) dynamically adapting to actual title/subtitle positions."""
    sub_bottom = 0.0
    title_bottom = 0.0
    for shape in getattr(slide, "placeholders", []):
        try:
            idx = shape.placeholder_format.idx
            if idx == 16:  # subtitle
                if shape.has_text_frame and shape.text.strip():
                    sub_bottom = max(sub_bottom, shape.top.inches + shape.height.inches)
            elif idx in (14, 15):  # title
                if shape.has_text_frame and shape.text.strip():
                    title_bottom = max(title_bottom, shape.top.inches + shape.height.inches)
        except Exception:
            pass

    if sub_bottom > 0.1:
        top = max(1.45, sub_bottom + 0.12)
    elif title_bottom > 0.1:
        top = max(1.45, title_bottom + 0.15)
    else:
        layout_name = slide.slide_layout.name if hasattr(slide, "slide_layout") else ""
        is_two_line = "Two-line" in layout_name or "2-line" in layout_name
        top = 1.68 if is_two_line else 1.45

    bottom = 6.25  # Leave ample space above footer and watermark at 6.45in
    return top, max(bottom - top, 2.5)


def _build_legacy_presentation(presentation: Any, result: PipelineResult) -> None:
    """Render older cached results that predate the AI presentation plan."""
    index = DocumentIndex(result.observations)
    usable_charts = _usable_charts(result)
    presentation_charts = usable_charts[:10]
    chart_groups = _group_chart_plans(presentation_charts, index)

    # Standard order: 1. Cover, 2. Contents, 3. Overview, 4. Analysis at a glance, 5. Findings
    _add_cover(presentation, result)
    _add_contents(presentation, result, chart_groups)
    if result.profile.document_summary.strip():
        _add_document_overview(presentation, result)
    _add_evidence_overview(presentation, result)
    _add_findings_slide(presentation, result, presentation_charts, index)
    if chart_groups:
        _add_section_divider(presentation, "Thematic analysis", "Connected measures, periods and source evidence")
    for ordinal, group in enumerate(chart_groups):
        if len(group) == 1:
            _add_chart_slide(presentation, group[0], index, ordinal=ordinal)
        else:
            _add_chart_cluster_slide(presentation, group, index)
    if not usable_charts:
        _add_no_chart_slide(presentation, result)
    _add_quality_slide(presentation, result)
    _add_section_divider(presentation, "Evidence appendix", "The retained values behind the charts")
    _add_evidence_table_slides(presentation, result, presentation_charts)


def _build_planned_presentation(presentation: Any, result: PipelineResult) -> None:
    """Render the validated AI narrative while keeping all evidence deterministic."""
    plan = result.presentation_plan
    if plan is None:  # pragma: no cover - guarded by caller
        return
    index = DocumentIndex(result.observations)
    chart_by_id = {item.id: item for item in _usable_charts(result)}
    slides_by_type = {slide.slide_type: slide for slide in plan.slides}

    # Standard order: 1. Cover, 2. Contents, 3. Company at a Glance, 4. Executive Summary
    cover = slides_by_type["cover"]
    _add_cover(presentation, result, title=cover.title, purpose=cover.message)
    _add_planned_contents(presentation, plan.slides)
    _add_company_at_a_glance(presentation, result, slides_by_type["company_overview"])
    _add_planned_summary(presentation, result, slides_by_type["executive_summary"], index)

    rendered_charts: list[ChartPlan] = []
    ordinal = 0
    for slide_plan in plan.slides[3:]:
        if slide_plan.slide_type == "analysis":
            chart_requests = _planned_chart_requests(slide_plan)
            requested_chart_ids = [identifier for identifier, _ in chart_requests]
            unavailable_chart_ids = set(requested_chart_ids) - chart_by_id.keys()
            if unavailable_chart_ids:
                raise ValueError(
                    "The presentation plan selected charts that did not pass the evidence checks: "
                    + ", ".join(sorted(unavailable_chart_ids))
                )
            charts = []
            for identifier, chart_type in chart_requests:
                if identifier not in chart_by_id:
                    continue
                chart = chart_by_id[identifier]
                if chart_type:
                    chart = chart.model_copy(update={"chart_type": chart_type})
                charts.append(chart)
            if charts:
                charts = [
                    item.model_copy(
                        update={
                            "title": slide_plan.title,
                            "question": slide_plan.message or item.question,
                            "source_pages": slide_plan.source_pages or item.source_pages,
                        }
                    )
                    for item in charts
                ]
                rendered_charts.extend(charts)
                if len(charts) == 1 and slide_plan.layout != "chart_with_data":
                    _add_chart_slide(
                        presentation,
                        charts[0],
                        index,
                        ordinal=ordinal,
                        title=slide_plan.title,
                        subtitle=slide_plan.message,
                    )
                else:
                    _add_chart_cluster_slide(
                        presentation,
                        charts,
                        index,
                        title=slide_plan.title,
                        subtitle=slide_plan.message,
                        layout=slide_plan.layout,
                        supporting_observations=_planned_observations(slide_plan, index),
                    )
                ordinal += 1
            else:
                observations = _planned_observations(slide_plan, index)
                if observations:
                    _add_planned_data_slide(presentation, slide_plan, observations)
                else:
                    _add_planned_text_slide(presentation, result, slide_plan)
        elif slide_plan.slide_type == "risks":
            _add_planned_text_slide(presentation, result, slide_plan)
        elif slide_plan.slide_type == "data_quality":
            _add_quality_slide(presentation, result, title=slide_plan.title)
        elif slide_plan.slide_type == "appendix":
            if rendered_charts:
                appendix_charts = rendered_charts
                _add_section_divider(presentation, "Evidence appendix", "The retained values behind the charts")
                _add_evidence_table_slides(presentation, result, appendix_charts, title=slide_plan.title)
            else:
                from adaptive_document_agent.models.validation import ValidationIssue

                result.validation_warnings.append(
                    ValidationIssue(
                        code="no_body_charts",
                        message="No charts were rendered in presentation body; appendix limited to representative evidence sample.",
                        severity="warning",
                        stage="presentation_export",
                    )
                )
                _add_evidence_table_slides(
                    presentation,
                    result,
                    [],
                    title="Representative retained evidence",
                    subtitle="Representative retained evidence (no charts in body)",
                    max_pages=1,
                )


def _planned_chart_requests(slide_plan: PresentationSlide) -> list[tuple[str, str | None]]:
    requests: list[tuple[str, str | None]] = [(identifier, None) for identifier in slide_plan.chart_ids]
    for block in slide_plan.visual_blocks:
        requests.extend((identifier, block.chart_type) for identifier in block.chart_ids)
    output: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    for identifier, chart_type in requests:
        if identifier in seen:
            continue
        seen.add(identifier)
        output.append((identifier, chart_type))
    return output[:3]


def _planned_observations(slide_plan: PresentationSlide, index: DocumentIndex) -> list[Observation]:
    identifiers = list(slide_plan.observation_ids)
    for block in slide_plan.visual_blocks:
        identifiers.extend(block.observation_ids)
    output: list[Observation] = []
    seen: set[str] = set()
    for identifier in identifiers:
        item = index.get(identifier)
        if item is not None and identifier not in seen:
            seen.add(identifier)
            output.append(item)
    return output


def _add_planned_contents(presentation: Any, planned_slides: list[PresentationSlide]) -> None:
    slide = _base_slide(presentation, "Contents", "Presentation structure")
    entries: list[str] = ["Company Overview"]
    seen = {"company overview"}
    defaults = {
        "analysis": "Analysis",
        "risks": "Key Risks and Watch Items",
        "data_quality": "Data Quality",
        "appendix": "Appendix",
    }
    for item in planned_slides:
        if item.slide_type not in defaults:
            continue
        label = (item.section_title or defaults[item.slide_type]).strip()
        # Clean section label: show section names only, not long slide titles
        if len(label) > 36:
            label = label.split(":", 1)[0].split("—", 1)[0].split("-", 1)[0].strip()
        key = label.casefold()
        if key not in seen:
            seen.add(key)
            entries.append(label)

    # Ensure Appendix is represented
    if "appendix" not in seen:
        entries.append("Appendix")

    # Balanced 2-column grid layout preventing overflow
    total_count = len(entries)
    items_per_col = max(5, (total_count + 1) // 2)
    card_h = min(0.68, (4.60 - (items_per_col - 1) * 0.12) / items_per_col)
    gap_y = 0.12
    top_start = 1.50

    for index, label in enumerate(entries):
        column = 0 if index < items_per_col else 1
        row = index if column == 0 else index - items_per_col
        left = 0.45 + column * 5.95
        top = top_start + row * (card_h + gap_y)
        _panel(slide, left, top, 5.65, card_h, fill=FOURIER_BG_CARD)
        _text(slide, f"{index + 1:02d}", left + 0.20, top + 0.14, 0.58, card_h - 0.20, size=14, color=FOURIER_PURPLE, bold=True)
        _text(slide, _summary_text(label, 42), left + 0.78, top + 0.14, 4.65, card_h - 0.20, size=13.5, color=FOURIER_DARK, bold=True)


def _add_company_at_a_glance(presentation: Any, result: PipelineResult, slide_plan: PresentationSlide) -> None:
    plan = result.presentation_plan
    if plan is None:  # pragma: no cover - guarded by caller
        return
    company = plan.company
    slide = _base_slide(presentation, slide_plan.title, company.document_type or result.profile.document_type)
    content_top, content_h = _content_zone(slide)

    name = company.name or result.profile.overview_title or "Company Overview"
    # Build a balanced, source-grounded description (2-4 concise lines)
    desc_candidates = [
        company.one_line_description,
        result.profile.document_summary,
        result.profile.document_purpose,
    ]
    desc_parts = [p.strip() for p in desc_candidates if p and p.strip()]
    description = ""
    seen_desc = set()
    for part in desc_parts:
        key = part.casefold()
        if key not in seen_desc and len(description) < 300:
            seen_desc.add(key)
            description = f"{description} {part}".strip() if description else part
    if not description:
        description = "Document-grounded overview of the reported issuer and business context."

    # Left card: Profile & Business snapshot
    _panel(slide, 0.45, content_top, 7.20, content_h, fill=FOURIER_BG_CARD)
    _text(slide, _summary_text(name, 80), 0.70, content_top + 0.20, 6.70, 0.55, size=22, color=FOURIER_DARK, bold=True)
    _text(slide, _summary_text(description, 360), 0.70, content_top + 0.85, 6.70, 1.40, size=13.5, color=FOURIER_MUTED)

    topics: list[str] = []
    seen_topics: set[str] = set()
    for topic in [*company.products, *company.segments, *company.geographies]:
        key = " ".join(topic.casefold().split())
        if topic.strip() and key not in seen_topics:
            seen_topics.add(key)
            topics.append(topic)
    if company.business_model:
        key = " ".join(company.business_model.casefold().split())
        if key not in seen_topics:
            topics.append(company.business_model)
    if topics:
        _text(slide, "BUSINESS FOCUS", 0.70, content_top + 2.45, 4.0, 0.26, size=10.5, color=FOURIER_PURPLE, bold=True)
        _rule(slide, 0.70, content_top + 2.75, 6.70, 0.01, FOURIER_BORDER)
        topic_text = "\n".join(f"{index:02d}  {_summary_text(item, 72)}" for index, item in enumerate(topics[:4], start=1))
        _text(slide, topic_text, 0.70, content_top + 2.85, 6.70, 1.50, size=12.5, color=FOURIER_DARK, bold=True)

    # Right card: Key facts
    facts = [
        ("Industry", company.industry),
        ("Headquarters", company.headquarters),
        ("Listing market", company.listing_market),
        ("Track record", company.track_record_period),
        *[(item.label, item.value) for item in company.key_facts],
    ]
    deduplicated_facts: list[tuple[str, str]] = []
    seen_facts: set[str] = set()
    for label, value in facts:
        key = label.casefold().strip()
        if value.strip() and key not in seen_facts:
            seen_facts.add(key)
            deduplicated_facts.append((label, value))
    facts = deduplicated_facts[:5]

    _panel(slide, 7.85, content_top, 4.30, content_h, fill=FOURIER_BG_CARD)
    _text(slide, "KEY FACTS", 8.10, content_top + 0.20, 3.80, 0.26, size=10.5, color=FOURIER_PURPLE, bold=True)
    _rule(slide, 8.10, content_top + 0.50, 3.80, 0.01, FOURIER_BORDER)
    fact_top = content_top + 0.62
    for label, value in facts:
        _text(slide, label.upper(), 8.10, fact_top, 3.80, 0.22, size=9, color=FOURIER_MUTED, bold=True)
        val_h = 0.50 if len(value) > 36 else 0.35
        _text(slide, _summary_text(value, 86), 8.10, fact_top + 0.20, 3.80, val_h, size=12.5, color=FOURIER_DARK, bold=True)
        fact_top += val_h + 0.28

    pages = sorted({*company.source_pages, *slide_plan.source_pages, *(page for fact in company.key_facts for page in fact.source_pages)})
    if pages:
        _text(slide, f"Source pages  {', '.join(map(str, pages))}", 0.45, 6.22, 11.70, 0.25, size=9.5, color=FOURIER_MUTED)


def _is_calc_artifact(text: str) -> bool:
    t = text.casefold()
    return any(
        term in t
        for term in (
            "slope",
            "intercept",
            "turning point",
            "turning_point",
            "turning points",
            "turning_points",
            "r-squared",
            "r_squared",
            "p-value",
            "residuals",
            "calculated result",
            "calculated change result",
            "based on extracted observations",
            "this is a calculated result",
            "internal calculation",
            "extracted observations",
            "generated metric",
            "debug",
            "parser",
        )
    )


def _sanitize_investor_narrative(text: str) -> str:
    clean = text
    for phrase, replacement in (
        ("Calculated change result: ", "Analysis indicates "),
        ("calculated change result: ", "analysis indicates "),
        ("Calculated change result", "Analysis indicates"),
        ("calculated result", "analysis indicates"),
        ("Based on extracted observations", "Based on reported disclosures"),
        ("based on extracted observations", "based on reported disclosures"),
        ("extracted observations", "reported disclosures"),
        ("retained facts", "reported data"),
        ("retained fact", "reported figure"),
        ("retained evidence", "source disclosures"),
    ):
        clean = re.sub(re.escape(phrase), replacement, clean, flags=re.IGNORECASE)
    return clean.strip()


def _add_planned_summary(
    presentation: Any,
    result: PipelineResult,
    slide_plan: PresentationSlide,
    index: DocumentIndex,
) -> None:
    slide = _base_slide(presentation, slide_plan.title, slide_plan.message)
    insight_by_id = {item.id: item for item in result.insights}
    raw_findings = [
        (insight_by_id[identifier].title, insight_by_id[identifier].narrative)
        for identifier in slide_plan.insight_ids
        if identifier in insight_by_id
    ]
    findings = [
        (_sanitize_investor_narrative(t), _sanitize_investor_narrative(n))
        for t, n in raw_findings
        if not _is_calc_artifact(t) and not _is_calc_artifact(n)
    ]
    if slide_plan.bullets:
        bullet_findings = [
            ("", _sanitize_investor_narrative(bullet))
            for bullet in slide_plan.bullets
            if bullet.strip() and not _is_calc_artifact(bullet)
        ]
        if len(bullet_findings) >= 3 or not findings:
            findings = bullet_findings
        else:
            findings = [*bullet_findings, *findings[: 5 - len(bullet_findings)]]
    if not findings:
        findings = [
            (str(item["title"]), str(item["narrative"]))
            for item in _chart_findings(_usable_charts(result), index)
            if not _is_calc_artifact(str(item["title"])) and not _is_calc_artifact(str(item["narrative"]))
        ]
    _add_numbered_messages(slide, findings[:5], source_pages=slide_plan.source_pages)


def _add_planned_data_slide(
    presentation: Any,
    slide_plan: PresentationSlide,
    observations: list[Observation],
) -> None:
    slide = _base_slide(presentation, slide_plan.title, slide_plan.message)
    content_top, content_h = _content_zone(slide)
    selected = observations[:8]
    card_h = min(1.00, (content_h - 3 * 0.12) / 4)

    for index, item in enumerate(selected):
        column = index % 2
        row = index // 2
        left = 0.45 + column * 5.95
        y = content_top + row * (card_h + 0.12)
        pages = ", ".join(map(str, sorted({source.page for source in item.evidence})))

        # Use metric semantic classifier to avoid "% of RMB" or labeling currency as percent
        semantic = classify_metric(
            display_metric_name(item),
            value=item.value,
            raw_unit=item.raw_unit,
            unit=item.unit,
        )
        metric_title = semantic.clean_name

        value_str = format_metric_display_value(
            item.raw_value,
            item.value,
            semantic,
            raw_unit=_display_source_unit(item),
            currency=item.currency,
        )

        # Format period cleanly (e.g. 30 Apr 2025*)
        is_bs = any(term in metric_title.casefold() for term in ("liabilit", "cash", "balance", "receiv", "payab", "inventor"))
        period_str = format_period_label(item.period, is_balance_sheet=is_bs)

        _panel(slide, left, y, 5.75, card_h, fill=FOURIER_BG_CARD)
        _text(slide, _summary_text(metric_title, 48), left + 0.20, y + 0.12, 3.60, 0.32, size=12, color=FOURIER_MUTED, bold=True)
        _text(slide, _summary_text(value_str, 42), left + 0.20, y + 0.46, 3.60, 0.45, size=19, color=FOURIER_DARK, bold=True)
        _text(slide, period_str or item.entity or "Reported value", left + 3.80, y + 0.50, 1.75, 0.30, size=11, color=FOURIER_TECH_BLUE, bold=True, align="right")
        if pages:
            _text(slide, f"p. {pages}", left + 4.30, y + 0.12, 1.25, 0.24, size=9, color=FOURIER_MUTED, align="right")


def _add_planned_text_slide(presentation: Any, result: PipelineResult, slide_plan: PresentationSlide) -> None:
    slide = _base_slide(presentation, slide_plan.title, slide_plan.message)
    insight_by_id = {item.id: item for item in result.insights}
    messages = [("", item) for item in slide_plan.bullets]
    if not messages:
        messages = [
            (insight_by_id[identifier].title, insight_by_id[identifier].narrative)
            for identifier in slide_plan.insight_ids
            if identifier in insight_by_id
        ]
    if not messages:
        messages = [("Evidence note", "The retained evidence supports this topic, but no additional narrative was supplied.")]

    is_risk_or_watch = slide_plan.slide_type == "risks" or "watch" in slide_plan.title.casefold()
    _add_numbered_messages(slide, messages[:5], source_pages=slide_plan.source_pages, is_interpretation=is_risk_or_watch)


def _add_numbered_messages(
    slide: Any,
    messages: list[tuple[str, str]],
    *,
    source_pages: list[int],
    is_interpretation: bool = False,
) -> None:
    content_top, content_h = _content_zone(slide)
    count = min(len(messages), 5)
    top = content_top
    if is_interpretation:
        top += 0.32
        content_h -= 0.32
        _text(slide, "ANALYTICAL INTERPRETATION  —  Based on reported movements, not standalone quotes", 0.45, content_top + 0.04, 8.50, 0.24, size=9, color=FOURIER_TECH_BLUE, bold=True)

    card_height = min(0.85, (content_h - (count - 1) * 0.12) / max(count, 1))
    for number, (label, narrative) in enumerate(messages[:count], start=1):
        y = top + (number - 1) * (card_height + 0.12)
        _panel(slide, 0.45, y, 11.70, card_height, fill=FOURIER_BG_CARD)
        _text(slide, f"{number:02d}", 0.65, y + 0.14, 0.55, 0.35, size=15, color=FOURIER_PURPLE, bold=True)
        sanitized_label = _sanitize_investor_narrative(label)
        sanitized_narrative = _sanitize_investor_narrative(narrative)
        if sanitized_label:
            _text(slide, _summary_text(sanitized_label, 50), 1.30, y + 0.12, 3.40, card_height - 0.20, size=13.5, color=FOURIER_DARK, bold=True)
            narrative_left, narrative_width = 4.85, 7.10
        else:
            narrative_left, narrative_width = 1.30, 10.65
        _text(slide, _summary_text(sanitized_narrative, 240), narrative_left, y + 0.12, narrative_width, card_height - 0.20, size=13, color=FOURIER_DARK)
    if source_pages:
        _text(slide, f"Source pages  {', '.join(map(str, source_pages))}", 0.45, 6.22, 11.70, 0.25, size=9.5, color=FOURIER_MUTED, align="right")


def _add_contents(presentation: Any, result: PipelineResult, groups: list[list[ChartPlan]]) -> None:
    slide = _base_slide(presentation, "Contents", "A structured path through the evidence")
    sections: list[tuple[str, str]] = []
    if result.profile.document_summary.strip():
        sections.append(("01", "Document overview"))
    sections.append((f"{len(sections) + 1:02d}", "Analysis at a glance"))
    sections.append((f"{len(sections) + 1:02d}", "Key findings"))
    if groups:
        sections.append((f"{len(sections) + 1:02d}", "Thematic analysis"))
    sections.append((f"{len(sections) + 1:02d}", "Data quality and limitations"))
    sections.append((f"{len(sections) + 1:02d}", "Evidence appendix"))

    total_count = len(sections)
    items_per_col = max(5, (total_count + 1) // 2)
    card_h = min(0.68, (4.60 - (items_per_col - 1) * 0.12) / items_per_col)
    gap_y = 0.12
    top_start = 1.50

    for index, (number, label) in enumerate(sections):
        column = 0 if index < items_per_col else 1
        row = index if column == 0 else index - items_per_col
        left = 0.45 + column * 5.95
        top = top_start + row * (card_h + gap_y)
        _panel(slide, left, top, 5.65, card_h, fill=FOURIER_BG_CARD)
        _text(slide, number, left + 0.20, top + 0.14, 0.58, card_h - 0.20, size=14, color=FOURIER_PURPLE, bold=True)
        _text(slide, label, left + 0.78, top + 0.14, 4.65, card_h - 0.20, size=13.5, color=FOURIER_DARK, bold=True)


def _add_section_divider(presentation: Any, title: str, subtitle: str) -> None:
    layout_idx = 11 if len(presentation.slide_layouts) > 11 else 0
    slide = presentation.slides.add_slide(presentation.slide_layouts[layout_idx])
    clean_title = _summary_text(title, 64)
    clean_subtitle = _summary_text(subtitle, 120) if subtitle else ""
    for ph in slide.placeholders:
        if ph.placeholder_format.idx == 15:
            ph.text = clean_title
            ph.text_frame.word_wrap = True
    if clean_subtitle:
        _text(slide, clean_subtitle, 0.50, 4.35, 11.60, 0.50, size=14, color=FOURIER_MUTED, align="center")


def _add_cover(
    presentation: Any,
    result: PipelineResult,
    *,
    title: str | None = None,
    purpose: str | None = None,
) -> None:
    from pptx.util import Inches, Pt

    slide = presentation.slides.add_slide(presentation.slide_layouts[0])
    cover_title = title or result.report_plan.title or result.profile.overview_title or "Adaptive Document Analysis"
    clean_title = _summary_text(cover_title, 72)
    clean_purpose = _summary_text(
        purpose or result.profile.document_purpose or result.profile.document_summary or "Intelligence derived from reported statements",
        180,
    )

    # Dynamic font scaling to prevent title overlap (max 2 lines)
    is_long_title = len(clean_title) > 36
    title_font_size = 28 if is_long_title else 36
    subtitle_top = 3.10 if is_long_title else 2.80

    ph16 = None
    ph15 = None
    for ph in slide.placeholders:
        if ph.placeholder_format.idx == 16:
            ph16 = ph
            ph.text = clean_title
            ph.left = Inches(0.30)
            ph.top = Inches(1.35)
            ph.width = Inches(6.85)
            ph.height = Inches(1.35 if is_long_title else 0.85)
            ph.text_frame.word_wrap = True
            if ph.text_frame.paragraphs:
                ph.text_frame.paragraphs[0].font.size = Pt(title_font_size)
        elif ph.placeholder_format.idx == 15:
            ph15 = ph
            ph.text = clean_purpose
            ph.left = Inches(0.30)
            ph.top = Inches(subtitle_top)
            ph.width = Inches(6.85)
            ph.height = Inches(0.95)
            ph.text_frame.word_wrap = True
            if ph.text_frame.paragraphs:
                ph.text_frame.paragraphs[0].font.size = Pt(14)

    if ph16 is not None and ph15 is not None:
        spTree = slide.shapes._spTree
        spTree.remove(ph16._element)
        spTree.insert(spTree.index(ph15._element), ph16._element)


def _add_evidence_overview(presentation: Any, result: PipelineResult) -> None:
    slide = _base_slide(presentation, "Analysis at a glance", "The retained evidence and current analytical scope")
    content_top, content_h = _content_zone(slide)

    metrics = {
        metric_key(item)
        for item in result.observations
        if metric_key(item) not in {"page", "pages"}
    }
    source_pages = {source.page for item in result.observations for source in item.evidence}
    values = [
        (str(len(result.observations)), "retained facts"),
        (str(len(metrics)), "distinct metrics"),
        (str(len(result.charts)), "validated charts"),
        (str(len(source_pages)), "evidence pages"),
    ]
    colors = (FOURIER_PURPLE, FOURIER_TECH_BLUE, FOURIER_AMBER, FOURIER_CYAN)
    card_w = (11.70 - 3 * 0.25) / 4
    for index, (value, label) in enumerate(values):
        left = 0.45 + index * (card_w + 0.25)
        _panel(slide, left, content_top, card_w, 1.30, fill=FOURIER_BG_CARD)
        _text(slide, value, left + 0.15, content_top + 0.15, card_w - 0.30, 0.60, size=30, color=colors[index], bold=True)
        _text(slide, label.upper(), left + 0.15, content_top + 0.80, card_w - 0.30, 0.35, size=10.5, color=FOURIER_MUTED, bold=True)

    purpose_top = content_top + 1.55
    purpose_h = content_h - 1.55
    _panel(slide, 0.45, purpose_top, 11.70, purpose_h, fill=FOURIER_BG_CARD)
    _text(slide, "DOCUMENT PURPOSE", 0.70, purpose_top + 0.20, 6.0, 0.26, size=10.5, color=FOURIER_PURPLE, bold=True)
    _text(slide, _summary_text(result.profile.document_purpose, 460), 0.70, purpose_top + 0.50, 7.20, purpose_h - 0.85, size=14, color=FOURIER_DARK)
    focus = _summary_text(result.profile.analysis_focus or "Automatic discovery", 280)
    _text(slide, "ANALYSIS FOCUS", 8.20, purpose_top + 0.20, 3.60, 0.26, size=10.5, color=FOURIER_TECH_BLUE, bold=True)
    _text(slide, focus, 8.20, purpose_top + 0.50, 3.60, purpose_h - 0.85, size=13.5, color=FOURIER_DARK)
    _text(slide, f"Pages reviewed  {_page_ranges(result)}", 0.70, 6.22, 11.20, 0.25, size=9.5, color=FOURIER_MUTED)


def _add_document_overview(presentation: Any, result: PipelineResult) -> None:
    title = _summary_text(result.profile.overview_title.strip() or "Document overview", 60)
    slide = _base_slide(presentation, title, result.profile.document_type)
    content_top, content_h = _content_zone(slide)

    _panel(slide, 0.45, content_top, 7.50, content_h, fill=FOURIER_BG_CARD)
    _text(slide, _summary_text(result.profile.document_summary, 650), 0.70, content_top + 0.20, 7.00, content_h - 0.45, size=14, color=FOURIER_DARK)

    _panel(slide, 8.15, content_top, 4.00, content_h, fill=FOURIER_BG_CARD)
    _text(slide, "TOPICS COVERED", 8.40, content_top + 0.20, 3.50, 0.26, size=10.5, color=FOURIER_PURPLE, bold=True)
    _rule(slide, 8.40, content_top + 0.50, 3.50, 0.01, FOURIER_BORDER)
    sections = [item for item in result.profile.important_sections if item.strip()][:5]
    section_text = "\n\n".join(f"{index:02d}  {_summary_text(section, 80)}" for index, section in enumerate(sections, start=1))
    _text(slide, section_text or "The analysis follows the document's discovered structure.", 8.40, content_top + 0.62, 3.50, content_h - 0.90, size=12.5, color=FOURIER_DARK)

    pages = ", ".join(map(str, sorted(set(result.profile.document_summary_pages))))
    if pages:
        _text(slide, f"Overview source pages  {pages}", 0.45, 6.22, 11.70, 0.25, size=9.5, color=FOURIER_MUTED)


def _add_chart_slide(
    presentation: Any,
    plan: ChartPlan,
    index: DocumentIndex,
    *,
    ordinal: int,
    title: str | None = None,
    subtitle: str | None = None,
) -> None:
    observations = [index.get(identifier) for identifier in plan.observation_ids]
    values = [item for item in observations if item and item.value is not None]
    display_title = title or _presentation_chart_title(plan.title, values)
    display_subtitle = subtitle or plan.question
    slide = _base_slide(presentation, display_title, display_subtitle)
    content_top, content_h = _content_zone(slide)

    if not values:
        _panel(slide, 0.45, content_top, 11.70, content_h, fill=FOURIER_BG_CARD)
        _text(slide, "The chart plan contains no usable values.", 0.85, 3.2, 10.9, 0.8, size=20, color=FOURIER_MUTED, align="center")
        return

    # Left card: Key movement & provenance
    _panel(slide, 0.45, content_top, 3.55, content_h, fill=FOURIER_BG_CARD)
    _text(slide, "KEY MOVEMENT", 0.70, content_top + 0.20, 3.05, 0.26, size=10.5, color=FOURIER_PURPLE, bold=True)
    _rule(slide, 0.70, content_top + 0.50, 3.05, 0.01, FOURIER_BORDER)

    max_abs = max(abs(float(item.value or 0)) for item in values)
    scale, scale_label = _display_scale(values, max_abs)
    movement = _change_summary(values, scale)
    unit = _unit_label(values, scale_label)
    pages = ", ".join(map(str, plan.source_pages)) or "not available"

    if movement:
        _text(slide, movement[0], 0.70, content_top + 0.65, 3.05, 0.70, size=26, color=FOURIER_PURPLE, bold=True)
        _text(slide, _summary_text(movement[1], 100), 0.70, content_top + 1.45, 3.05, 0.90, size=13, color=FOURIER_DARK)
    else:
        _text(slide, f"{len(values)}", 0.70, content_top + 0.65, 3.05, 0.70, size=26, color=FOURIER_TECH_BLUE, bold=True)
        _text(slide, "comparable reported observations", 0.70, content_top + 1.45, 3.05, 0.90, size=13, color=FOURIER_DARK)

    _text(slide, "REPORTED UNIT", 0.70, content_top + 2.75, 3.05, 0.24, size=9.5, color=FOURIER_MUTED, bold=True)
    _text(slide, unit, 0.70, content_top + 3.00, 3.05, 0.45, size=12, color=FOURIER_DARK, bold=True)
    _text(slide, f"Source pages  {pages}", 0.70, content_top + content_h - 0.45, 3.05, 0.35, size=9.5, color=FOURIER_MUTED)

    # Right card: Chart (no background gridlines)
    _panel(slide, 4.20, content_top, 7.95, content_h, fill=WHITE)
    chart_bounds = (4.40, content_top + 0.15, 7.55, content_h - 0.30)
    _add_native_chart(slide, plan, values, chart_bounds)


def _add_chart_cluster_slide(
    presentation: Any,
    plans: list[ChartPlan],
    index: DocumentIndex,
    *,
    title: str | None = None,
    subtitle: str | None = None,
    layout: str = "auto",
    supporting_observations: list[Observation] | None = None,
) -> None:
    slide = _base_slide(
        presentation,
        title or _chart_group_title(plans, index),
        subtitle or "A coordinated view across comparable reported periods",
    )
    content_top, content_h = _content_zone(slide)
    count = min(len(plans), 3)
    gap = 0.25
    total_w = 11.70
    panel_w = (total_w - gap * (count - 1)) / count
    panel_bounds = [(0.45 + pos * (panel_w + gap), content_top, panel_w, content_h) for pos in range(count)]

    for position, (plan, bounds) in enumerate(zip(plans[:count], panel_bounds)):
        observations = [index.get(identifier) for identifier in plan.observation_ids]
        values = [item for item in observations if item and item.value is not None]
        left, top, panel_width, panel_height = bounds
        _panel(slide, left, top, panel_width, panel_height, fill=FOURIER_BG_CARD)
        chart_title = _presentation_chart_title(plan.title, values)
        compact_panel = panel_width < 4.5
        _text(
            slide,
            _summary_text(chart_title, 48 if not compact_panel else 36),
            left + 0.18,
            top + 0.15,
            panel_width - 0.36,
            0.42,
            size=13.5 if not compact_panel else 12,
            color=FOURIER_DARK,
            bold=True,
        )
        if not values:
            _text(slide, "No usable values", left + 0.18, top + panel_height / 2, panel_width - 0.36, 0.4, size=12, color=FOURIER_MUTED, align="center")
            continue
        footer_height = 0.65
        chart_bounds = (left + 0.15, top + 0.60, panel_width - 0.30, panel_height - 0.70 - footer_height)
        scale, scale_label = _add_native_chart(slide, plan, values, chart_bounds, compact=True)
        movement = _change_summary(values, scale)
        unit = _unit_label(values, scale_label)
        pages = ", ".join(map(str, plan.source_pages)) or "not available"
        footer_top = top + panel_height - footer_height + 0.05
        if movement:
            _text(slide, movement[0], left + 0.18, footer_top, panel_width * 0.45, 0.28, size=12, color=CHART_PALETTE[position % len(CHART_PALETTE)], bold=True)
            _text(slide, _summary_text(movement[1], 48), left + panel_width * 0.45, footer_top, panel_width * 0.50, 0.28, size=9, color=FOURIER_DARK, align="right")
            footer_top += 0.26
        _text(slide, _summary_text(unit, 36), left + 0.18, footer_top, panel_width - 1.10, 0.22, size=8.5, color=FOURIER_MUTED)
        _text(slide, f"p. {pages}", left + panel_width - 1.00, footer_top, 0.85, 0.22, size=8.5, color=FOURIER_MUTED, align="right")


def _add_native_chart(
    slide: Any,
    plan: ChartPlan,
    values: list[Observation],
    bounds: tuple[float, float, float, float],
    *,
    compact: bool = False,
) -> tuple[float, str]:
    from pptx.chart.data import CategoryChartData, XyChartData
    from pptx.enum.chart import XL_CHART_TYPE, XL_DATA_LABEL_POSITION, XL_LEGEND_POSITION
    from pptx.util import Inches, Pt

    max_abs = max(abs(float(item.value or 0)) for item in values)
    scale, scale_label = _display_scale(values, max_abs)
    chart_left, chart_top, chart_width, chart_height = (Inches(value) for value in bounds)

    # Detect balance sheet metric for interim date formatting
    metric_name = plan.title or (values[0].metric_original if values else "")
    is_bs = any(term in metric_name.casefold() for term in ("liabilit", "cash", "balance", "receiv", "payab", "inventor"))

    if plan.chart_type == "scatter" and plan.x_metric and plan.y_metric:
        data = XyChartData()
        series = data.add_series("Observed pairs")
        for left, right in paired_observations(values, plan.x_metric, plan.y_metric):
            series.add_data_point(float(left.value or 0) / scale, float(right.value or 0) / scale)
        chart = slide.shapes.add_chart(XL_CHART_TYPE.XY_SCATTER, chart_left, chart_top, chart_width, chart_height, data).chart
    else:
        rows = _series_rows(plan, values, is_balance_sheet=is_bs)
        categories = list(dict.fromkeys(row[0] for row in rows))
        series_names = list(dict.fromkeys(row[1] for row in rows))
        data = CategoryChartData()
        data.categories = categories
        for name in series_names:
            lookup = {label: value for label, series_name, value in rows if series_name == name}
            data.add_series(name, [lookup.get(label) / scale if lookup.get(label) is not None else None for label in categories])
        chart_type = {
            "line": XL_CHART_TYPE.LINE_MARKERS,
            "area": XL_CHART_TYPE.AREA,
            "pie": XL_CHART_TYPE.PIE,
            "horizontal_bar": XL_CHART_TYPE.BAR_CLUSTERED,
        }.get(plan.chart_type, XL_CHART_TYPE.COLUMN_CLUSTERED)
        chart = slide.shapes.add_chart(chart_type, chart_left, chart_top, chart_width, chart_height, data).chart

    chart.has_title = False
    _normalize_axis_ids(chart)
    chart.has_legend = len(getattr(chart, "series", [])) > 1
    if chart.has_legend:
        chart.legend.position = XL_LEGEND_POSITION.BOTTOM
        chart.legend.font.name = FONT
        chart.legend.font.size = Pt(8 if compact else 10)
    chart.chart_style = 10
    for series_index, series in enumerate(chart.series):
        color = CHART_PALETTE[series_index % len(CHART_PALETTE)]
        try:
            series.format.fill.solid()
            series.format.fill.fore_color.rgb = _rgb(color)
            series.format.line.color.rgb = _rgb(color)
        except (AttributeError, ValueError):
            pass
    try:
        chart.plots[0].has_data_labels = plan.show_data_labels
        labels = chart.plots[0].data_labels
        if plan.chart_type == "pie":
            labels.position = XL_DATA_LABEL_POSITION.BEST_FIT
        elif plan.chart_type in {"line", "area"}:
            labels.position = XL_DATA_LABEL_POSITION.ABOVE
        else:
            labels.position = XL_DATA_LABEL_POSITION.OUTSIDE_END
        labels.font.name = FONT
        labels.font.size = Pt(8 if compact else 10)
        labels.number_format = "0.0"
    except (AttributeError, ValueError):
        pass
    try:
        # Style axis fonts and DISABLE ALL BACKGROUND GRIDLINES
        if hasattr(chart, "category_axis") and chart.category_axis is not None:
            chart.category_axis.tick_labels.font.name = FONT
            chart.category_axis.tick_labels.font.size = Pt(8 if compact else 10)
            chart.category_axis.has_major_gridlines = False
            chart.category_axis.has_minor_gridlines = False

        if hasattr(chart, "value_axis") and chart.value_axis is not None:
            chart.value_axis.tick_labels.font.name = FONT
            chart.value_axis.tick_labels.font.size = Pt(8 if compact else 10)
            chart.value_axis.tick_labels.number_format = "0.0"
            chart.value_axis.tick_labels.number_format_is_linked = False
            # Clean institutional styling: NO BACKGROUND HORIZONTAL GRIDLINES
            chart.value_axis.has_major_gridlines = False
            chart.value_axis.has_minor_gridlines = False
            chart.value_axis.axis_title.text_frame.paragraphs[0].text = ""
    except (AttributeError, ValueError):
        pass
    return scale, scale_label


def _add_no_chart_slide(presentation: Any, result: PipelineResult) -> None:
    slide = _base_slide(presentation, "Analysis overview", "Evidence-grounded observations")
    content_top, content_h = _content_zone(slide)
    _panel(slide, 0.45, content_top, 11.70, content_h, fill=FOURIER_BG_CARD)
    _text(slide, "No chart passed the evidence checks", 0.85, content_top + 0.60, 10.9, 0.70, size=24, color=FOURIER_DARK, bold=True)
    _text(
        slide,
        "The presentation preserves this outcome instead of drawing unsupported comparisons. Review the extracted periods, units and validation warnings before using the data for decisions.",
        0.85,
        content_top + 1.45,
        10.9,
        1.20,
        size=14.5,
        color=FOURIER_MUTED,
    )


def _add_findings_slide(
    presentation: Any,
    result: PipelineResult,
    charts: list[ChartPlan],
    index: DocumentIndex,
) -> None:
    slide = _base_slide(presentation, "Key findings", "Evidence-backed conclusions from the analysis")
    content_top, content_h = _content_zone(slide)
    findings = _chart_findings(charts, index)
    seen_titles = {str(item["title"]).casefold() for item in findings}
    model_findings = [
        {
            "title": finding.title,
            "narrative": finding.narrative,
            "pages": sorted({source.page for source in finding.evidence}),
        }
        for finding in sorted(result.insights, key=lambda item: (item.importance, item.confidence), reverse=True)
    ]
    for finding in model_findings:
        if len(findings) >= 4:
            break
        candidate_title = str(finding["title"]).casefold()
        if any(
            candidate_title == existing
            or candidate_title.startswith(f"{existing} ")
            or existing.startswith(f"{candidate_title} ")
            for existing in seen_titles
        ):
            continue
        findings.append(finding)
        seen_titles.add(str(finding["title"]).casefold())
    if not findings:
        _panel(slide, 0.45, content_top, 11.70, content_h, fill=FOURIER_BG_CARD)
        _text(slide, "No validated analytical findings were produced.", 0.9, 3.2, 10.8, 0.8, size=20, color=FOURIER_MUTED, align="center")
        return
    count = len(findings)
    card_height = min(0.95, (content_h - (count - 1) * 0.12) / max(count, 1))
    top = content_top
    for number, finding in enumerate(findings, start=1):
        y = top + (number - 1) * (card_height + 0.12)
        _panel(slide, 0.45, y, 11.70, card_height, fill=FOURIER_BG_CARD)
        _text(slide, f"{number:02d}", 0.65, y + 0.15, 0.55, 0.35, size=15, color=FOURIER_PURPLE, bold=True)
        title_text = _sanitize_investor_narrative(str(finding["title"]))
        narrative_text = _sanitize_investor_narrative(str(finding["narrative"]))
        _text(slide, _summary_text(title_text, 55), 1.30, y + 0.12, 3.80, card_height - 0.20, size=13.5, color=FOURIER_DARK, bold=True)
        pages = list(finding.get("pages", []))
        source = f"Pages {', '.join(map(str, pages))}" if pages else "Calculated from retained evidence"
        _text(slide, _summary_text(narrative_text, 160), 5.25, y + 0.12, 5.20, card_height - 0.20, size=13, color=FOURIER_DARK)
        _text(slide, source, 10.55, y + 0.15, 1.45, 0.35, size=8.5, color=FOURIER_MUTED, align="right")


def _add_quality_slide(presentation: Any, result: PipelineResult, *, title: str = "Limits that affect interpretation") -> None:
    slide = _base_slide(presentation, title, "Data quality notes and validation warnings")
    content_top, content_h = _content_zone(slide)
    raw_messages = list(dict.fromkeys([
        *result.profile.data_quality_notes,
        *(warning.message for warning in result.validation_warnings if warning.severity in {"error", "warning"}),
    ]))[:5]

    # Clean wording: resolve company name issue if company is identified
    company_name = result.presentation_plan.company.name if result.presentation_plan and result.presentation_plan.company else ""
    messages = []
    for msg in raw_messages:
        if "issuer/company name is not stated" in msg.casefold() or "company name is not stated" in msg.casefold():
            if company_name and company_name != "Company overview":
                messages.append(
                    "The company is identified in introductory/source pages, while many pages within the Financial Information section refer only to the Company or Group."
                )
            else:
                messages.append(msg)
        else:
            messages.append(msg)

    if not messages:
        messages = ["No material data-quality warning was retained for this analysis."]
    top = content_top
    count = len(messages)
    card_h = min(0.85, (content_h - (count - 1) * 0.12) / max(count, 1))
    for index, message in enumerate(messages, start=1):
        y = top + (index - 1) * (card_h + 0.12)
        _panel(slide, 0.45, y, 11.70, card_h, fill=FOURIER_BG_CARD)
        _text(slide, f"{index:02d}", 0.65, y + 0.18, 0.55, 0.35, size=15, color=FOURIER_AMBER, bold=True)
        # Larger readable body text
        _text(slide, _summary_text(message, 360), 1.35, y + 0.14, 10.55, card_h - 0.20, size=14, color=FOURIER_DARK)


def _add_evidence_table_slides(
    presentation: Any,
    result: PipelineResult,
    charts: list[ChartPlan],
    *,
    title: str = "Key data appendix",
    subtitle: str | None = None,
    max_pages: int | None = None,
) -> None:
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.util import Inches

    observations = _appendix_observations(result, charts)
    if not observations:
        slide = _base_slide(presentation, title, subtitle or "Source-grounded evidence base")
        content_top, content_h = _content_zone(slide)
        _panel(slide, 0.45, content_top, 11.70, min(2.5, content_h), fill=FOURIER_BG_CARD)
        _text(
            slide,
            "No chart-grade structured observations were retained. See Data Quality for extraction limitations.",
            0.85,
            content_top + 0.80,
            10.9,
            0.8,
            size=15,
            color=FOURIER_MUTED,
            align="center",
        )
        _text(slide, "The CSV export contains the complete reported dataset.", 0.45, 6.22, 11.70, 0.25, size=9.5, color=FOURIER_MUTED)
        return

    page_size = 10
    pages = [observations[index:index + page_size] for index in range(0, len(observations), page_size)]
    if max_pages is not None:
        pages = pages[:max_pages]
    headers = ["Metric", "Period", "Reported value", "Unit", "Page"]

    for page_number, page_observations in enumerate(pages, start=1):
        slide_subtitle = subtitle or "Validated reported values used by the presentation charts, with page-level provenance"
        if subtitle is None and len(pages) > 1:
            slide_subtitle += f" | Appendix {page_number} of {len(pages)}"
        slide = _base_slide(presentation, title, slide_subtitle)
        content_top, content_h = _content_zone(slide)

        rows = []
        for item in page_observations:
            semantic = classify_metric(
                display_metric_name(item),
                value=item.value,
                raw_unit=item.raw_unit,
                unit=item.unit,
            )
            is_bs = any(term in semantic.clean_name.casefold() for term in ("liabilit", "cash", "balance", "receiv", "payab", "inventor"))
            period_label = format_period_label(item.period, is_balance_sheet=is_bs)
            rows.append([
                _summary_text(semantic.clean_name, 58),
                period_label or item.entity or "-",
                item.raw_value,
                _display_source_unit(item),
                ", ".join(map(str, sorted({source.page for source in item.evidence}))),
            ])

        table_top = content_top
        table_h = min(4.50, content_h - 0.35)
        table_shape = slide.shapes.add_table(len(rows) + 1, len(headers), Inches(0.45), Inches(table_top), Inches(11.70), Inches(table_h))
        table = table_shape.table

        # Client-aligned proportions: Metric 36%, Period 15%, Reported Value 22%, Unit 19%, Page 8%
        widths = [4.21, 1.76, 2.57, 2.22, 0.94]
        for column, width in zip(table.columns, widths):
            column.width = Inches(width)
        for column, header in enumerate(headers):
            cell = table.cell(0, column)
            cell.text = header
            _cell_style(cell, fill=FOURIER_PURPLE, color=WHITE, bold=True, size=11.5)
            if column in {2, 4}:
                cell.text_frame.paragraphs[0].alignment = PP_ALIGN.RIGHT
        for row_index, values in enumerate(rows, start=1):
            for column, value in enumerate(values):
                cell = table.cell(row_index, column)
                cell.text = str(value)
                _cell_style(cell, fill=WHITE if row_index % 2 else FOURIER_BG_CARD, color=FOURIER_DARK, bold=False, size=10.5)
                cell.vertical_anchor = MSO_ANCHOR.MIDDLE
                cell.text_frame.paragraphs[0].alignment = PP_ALIGN.RIGHT if column in {2, 4} else PP_ALIGN.LEFT
        row_height = min(0.45, 4.60 / max(len(rows) + 1, 1))
        for row in table.rows:
            row.height = Inches(row_height)
        _text(slide, "The CSV export contains the complete reported dataset.", 0.45, 6.22, 11.70, 0.25, size=9.5, color=FOURIER_MUTED)


def update_geometry(
    shape: Any,
    *,
    left: float | Any | None = None,
    top: float | Any | None = None,
    width: float | Any | None = None,
    height: float | Any | None = None,
) -> None:
    """Safely update shape geometry preserving unspecified dimensions.

    For python-pptx placeholder shapes inheriting transforms from slide layout,
    modifying any single dimension creates a new <a:xfrm> element with all other
    dimensions 0. Capturing all four dimensions BEFORE modifying ensures inherited
    geometry is preserved, preventing width or height from collapsing to zero.
    """
    cur_left = shape.left
    cur_top = shape.top
    cur_width = shape.width
    cur_height = shape.height

    from pptx.util import Inches
    new_left = Inches(left) if isinstance(left, (int, float)) else (left if left is not None else cur_left)
    new_top = Inches(top) if isinstance(top, (int, float)) else (top if top is not None else cur_top)
    new_width = Inches(width) if isinstance(width, (int, float)) else (width if width is not None else cur_width)
    new_height = Inches(height) if isinstance(height, (int, float)) else (height if height is not None else cur_height)

    # Invariants: ensure width and height never collapse to 0
    if hasattr(new_width, "inches") and new_width.inches <= 0.05:
        new_width = Inches(8.5)
    if hasattr(new_height, "inches") and new_height.inches <= 0.05:
        new_height = Inches(0.40)

    shape.left = new_left
    shape.top = new_top
    shape.width = new_width
    shape.height = new_height


def _base_slide(presentation: Any, title: str, subtitle: str = "", *, background: str | None = None) -> Any:
    clean_title = _summary_text(title, 118)
    clean_subtitle = _summary_text(subtitle, 175) if subtitle else ""
    layout_idx = 5 if len(clean_title) <= 52 else 6
    if layout_idx < len(presentation.slide_layouts):
        slide = presentation.slides.add_slide(presentation.slide_layouts[layout_idx])
    else:
        slide = presentation.slides.add_slide(presentation.slide_layouts[0])

    title_ph = None
    sub_ph = None
    for ph in slide.placeholders:
        if ph.placeholder_format.idx in (14, 15):
            title_ph = ph
        elif ph.placeholder_format.idx == 16:
            sub_ph = ph

    if title_ph is not None:
        title_ph.text = clean_title
        title_ph.text_frame.word_wrap = True
        title_len = len(clean_title)
        if title_len <= 45:
            title_size = 20.0
            title_h = 0.48
        elif title_len <= 80:
            title_size = 17.5
            title_h = 0.76
        else:
            title_size = 15.0
            title_h = 0.98
        update_geometry(title_ph, height=title_h)
        for p in title_ph.text_frame.paragraphs:
            p.font.size = Pt(title_size)

    if sub_ph is not None:
        if clean_subtitle:
            sub_ph.text = clean_subtitle
            sub_ph.text_frame.word_wrap = True
            for p in sub_ph.text_frame.paragraphs:
                p.font.size = Pt(11.0)
            sub_h = 0.50 if len(clean_subtitle) > 85 else None
            if title_ph is not None:
                title_top = title_ph.top.inches if hasattr(title_ph.top, "inches") else float(title_ph.top) / 914400.0
                title_h_in = title_ph.height.inches if hasattr(title_ph.height, "inches") else float(title_ph.height) / 914400.0
                sub_top = title_top + title_h_in + 0.08
                update_geometry(sub_ph, top=sub_top, height=sub_h)
            elif sub_h is not None:
                update_geometry(sub_ph, height=sub_h)
        else:
            sub_ph.text = ""
    return slide


def _text(
    slide: Any,
    value: str,
    left: float,
    top: float,
    width: float,
    height: float,
    *,
    size: float,
    color: str,
    bold: bool = False,
    font: str = FONT,
    align: str = "left",
) -> Any:
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.util import Inches, Pt

    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    frame = box.text_frame
    frame.clear()
    frame.word_wrap = True
    frame.margin_left = frame.margin_right = Inches(0.02)
    frame.margin_top = frame.margin_bottom = Inches(0.01)
    frame.vertical_anchor = MSO_ANCHOR.TOP
    paragraph = frame.paragraphs[0]
    paragraph.text = value
    paragraph.alignment = {"left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT}[align]
    paragraph.font.name = font
    paragraph.font.size = Pt(size)
    paragraph.font.bold = bold
    paragraph.font.color.rgb = _rgb(color)
    return box


def _rule(slide: Any, left: float, top: float, width: float, height: float, color: str) -> None:
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Inches

    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(left), Inches(top), Inches(width), Inches(height))
    _solid_shape(shape, color)


def _panel(slide: Any, left: float, top: float, width: float, height: float, *, fill: str) -> Any:
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Inches

    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(left), Inches(top), Inches(width), Inches(height))
    shape.fill.solid()
    shape.fill.fore_color.rgb = _rgb(fill)
    shape.line.color.rgb = _rgb(FOURIER_BORDER)
    shape.line.width = Inches(0.01)
    try:
        shape.adjustments[0] = 0.04
    except Exception:
        pass
    try:
        style = shape.element.find("{http://schemas.openxmlformats.org/presentationml/2006/main}style")
        if style is not None:
            effect_ref = style.find("{http://schemas.openxmlformats.org/drawingml/2006/main}effectRef")
            if effect_ref is not None:
                effect_ref.set("idx", "0")
    except Exception:
        pass
    return shape


def _solid_shape(shape: Any, color: str) -> None:
    shape.fill.solid()
    shape.fill.fore_color.rgb = _rgb(color)
    shape.line.fill.background()


def _background(slide: Any, color: str) -> None:
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = _rgb(color)


def _rgb(value: str) -> Any:
    from pptx.dml.color import RGBColor

    return RGBColor.from_string(value)


def _normalize_axis_ids(chart: Any) -> None:
    for element in chart._chartSpace.iter():
        if element.tag.rsplit("}", 1)[-1] not in {"axId", "crossAx"}:
            continue
        value = element.get("val")
        if value and value.startswith("-"):
            element.set("val", str(abs(int(value))))


def _series_name(base: str, dimensions: tuple[tuple[str, str], ...]) -> str:
    clean_base = sanitize_metric_label(base)
    if not dimensions:
        return clean_base
    details = ", ".join(
        f"{name.replace('_', ' ').title()}: {value}" for name, value in dimensions
    )
    return f"{clean_base} ({details})"


def _series_rows(plan: ChartPlan, observations: list[Observation], *, is_balance_sheet: bool = False) -> list[tuple[str, str, float]]:
    best: dict[tuple[str, str, tuple[tuple[str, str], ...]], Observation] = {}
    for item in sorted(observations, key=lambda value: period_sort_key(value.period)):
        axis_dimension = plan.x_dimension
        label = item.dimensions.get(axis_dimension) if axis_dimension else None
        if not label and item.period:
            label = item.period
        if not label and item.dimensions:
            axis_dimension, label = next(iter(item.dimensions.items()))
        label = label or item.entity or item.metric_original

        # Format label with interim notation if applicable
        label = format_period_label(label, is_balance_sheet=is_balance_sheet)

        base_series = str(item.entity or display_metric_name(item))
        ignored_dimensions = {axis_dimension, "table_context", "period_basis"}
        repeated_values = {
            str(value).strip().casefold()
            for value in (label, item.period, item.entity, base_series)
            if value is not None and str(value).strip()
        }
        dimensions = tuple(
            sorted(
                (
                    key,
                    str(value).strip(),
                )
                for key, value in item.dimensions.items()
                if key not in ignored_dimensions
                and str(value).strip()
                and str(value).strip().casefold() not in repeated_values
            )
        )
        key = (str(label), base_series, dimensions)
        current = best.get(key)
        if current is None or item.confidence > current.confidence:
            best[key] = item
    return [
        (label, _series_name(base_series, dimensions), float(item.value or 0))
        for (label, base_series, dimensions), item in best.items()
    ]


def _presentation_chart_title(title: str, observations: list[Observation]) -> str:
    series_names = {display_metric_name(item) for item in observations}
    if len(series_names) == 1:
        single = next(iter(series_names))
        if single.casefold() not in title.casefold():
            return _summary_text(f"{title} - {single}", 78)
    return _summary_text(title, 78)


def _chart_group_title(plans: list[ChartPlan], index: DocumentIndex) -> str:
    labels: list[str] = []
    for plan in plans:
        observations = [index.get(identifier) for identifier in plan.observation_ids]
        values = [item for item in observations if item and item.value is not None]
        labels.append(_presentation_chart_title(plan.title, values))
    common_prefix = os.path.commonprefix(labels).strip(" -:,")
    if len(common_prefix) >= 4:
        title = common_prefix
    elif len(labels) == 2:
        title = f"{labels[0]} and {labels[1]}"
    else:
        title = labels[0]
    if " — " in title and len(title) > 72:
        title = title.split(" — ", 1)[1]
    return _summary_text(title, 78)


def _change_summary(observations: list[Observation], scale: float) -> tuple[str, str] | None:
    series_names = {metric_key(item) for item in observations}
    if len(series_names) != 1:
        return None
    by_period: dict[str, Observation] = {}
    for item in observations:
        if item.period and item.value is not None:
            current = by_period.get(item.period)
            if current is None or item.confidence > current.confidence:
                by_period[item.period] = item
    ordered = sorted(by_period.values(), key=lambda item: period_sort_key(item.period))
    if len(ordered) < 2:
        return None
    first, last = ordered[0], ordered[-1]
    start, end = float(first.value or 0), float(last.value or 0)

    # Check metric semantic
    semantic = classify_metric(first.metric_original, value=start, raw_unit=first.raw_unit, unit=first.unit)
    headline = format_metric_change(start, end, scale, semantic)

    p_first = format_period_label(first.period)
    p_last = format_period_label(last.period)
    if semantic.is_multiple:
        detail = f"{start:.2f}x in {p_first} to {end:.2f}x in {p_last}"
    elif semantic.is_percentage:
        detail = f"{start:.1f}% in {p_first} to {end:.1f}% in {p_last}"
    else:
        detail = f"{_format_scaled(start, scale)} in {p_first} to {_format_scaled(end, scale)} in {p_last}"
    return headline, detail


def _format_scaled(value: float, scale: float) -> str:
    scaled = value / scale
    if abs(scaled) >= 100:
        return f"{scaled:,.0f}"
    if abs(scaled) >= 10:
        return f"{scaled:,.1f}"
    return f"{scaled:,.2f}"


def _group_chart_plans(plans: list[ChartPlan], index: DocumentIndex) -> list[list[ChartPlan]]:
    remaining = list(plans)
    groups: list[list[ChartPlan]] = []
    while remaining:
        anchor = remaining.pop(0)
        group = [anchor]
        for candidate in list(remaining):
            if len(group) >= 3:
                break
            if all(_charts_belong_together(member, candidate, index) for member in group):
                group.append(candidate)
                remaining.remove(candidate)
        groups.append(group)
    return groups


def _charts_belong_together(left: ChartPlan, right: ChartPlan, index: DocumentIndex) -> bool:
    if set(left.observation_ids) == set(right.observation_ids):
        return False
    left_values = [index.get(identifier) for identifier in left.observation_ids]
    right_values = [index.get(identifier) for identifier in right.observation_ids]
    left_values = [item for item in left_values if item and item.value is not None]
    right_values = [item for item in right_values if item and item.value is not None]
    if not left_values or not right_values:
        return False

    left_contexts = _chart_contexts(left_values)
    right_contexts = _chart_contexts(right_values)
    shared_context = bool(left_contexts & right_contexts)
    left_periods = {item.period for item in left_values if item.period}
    right_periods = {item.period for item in right_values if item.period}
    if left_periods and right_periods:
        overlap = len(left_periods & right_periods) / len(left_periods | right_periods)
        snapshot_of_trend = (
            len(left_periods) == 1 and left_periods <= right_periods
        ) or (
            len(right_periods) == 1 and right_periods <= left_periods
        )
        if overlap < 0.6 and not (shared_context and snapshot_of_trend):
            return False

    if shared_context:
        return True

    same_page = bool(_chart_source_pages(left, left_values) & _chart_source_pages(right, right_values))
    same_unit = _chart_unit_signature(left_values) == _chart_unit_signature(right_values)
    shared_terms = _chart_title_tokens(left, left_values) & _chart_title_tokens(right, right_values)
    return same_page and same_unit and bool(shared_terms)


def _chart_contexts(values: list[Observation]) -> set[str]:
    return {
        " ".join(item.dimensions.get("table_context", "").casefold().split())
        for item in values
        if item.dimensions.get("table_context", "").strip()
    }


def _chart_unit_signature(values: list[Observation]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    return (
        tuple(sorted({item.currency or "" for item in values})),
        tuple(sorted({item.unit or "" for item in values})),
    )


def _chart_source_pages(plan: ChartPlan, values: list[Observation]) -> set[int]:
    return {
        *plan.source_pages,
        *(source.page for item in values for source in item.evidence),
    }


def _chart_title_tokens(plan: ChartPlan, values: list[Observation]) -> set[str]:
    labels = " ".join([plan.title, *(display_metric_name(item) for item in values)])
    ignored = {"and", "the", "reported", "values", "value", "analysis", "chart", "total"}
    return {
        token
        for token in re.findall(r"[^\W_]{2,}", labels.casefold(), flags=re.UNICODE)
        if token not in ignored
    }


def _chart_group_title(plans: list[ChartPlan], index: DocumentIndex) -> str:
    value_sets = [
        [item for identifier in plan.observation_ids if (item := index.get(identifier)) and item.value is not None]
        for plan in plans
    ]
    common_contexts: set[str] | None = None
    display_contexts: dict[str, str] = {}
    for values in value_sets:
        contexts = _chart_contexts(values)
        for item in values:
            context = " ".join(item.dimensions.get("table_context", "").split())
            if context:
                display_contexts[context.casefold()] = context
        common_contexts = contexts if common_contexts is None else common_contexts & contexts
    if common_contexts:
        context = display_contexts[next(iter(common_contexts))]
        generic_context = re.sub(r"[^a-z0-9 ]", "", context.casefold()).strip()
        if 4 <= len(context) <= 72 and generic_context not in {
            "financial information",
            "financial information section",
            "financial results",
            "analysis",
        }:
            return context

    titles = [_presentation_chart_title(plan.title, values) for plan, values in zip(plans, value_sets)]
    if len(titles) == 2:
        return _summary_text(f"{titles[0]} and {titles[1]}", 72)
    return _summary_text(f"{titles[0]} and related measures", 72)


def _usable_charts(result: PipelineResult) -> list[ChartPlan]:
    index = DocumentIndex(result.observations)
    output: list[ChartPlan] = []
    for plan in result.charts:
        observations = [index.get(identifier) for identifier in plan.observation_ids]
        observations = [item for item in observations if item and is_meaningful_metric(item)]
        contexts = {
            (item.period, item.entity, tuple(sorted(item.dimensions.items())))
            for item in observations
            if item and item.value is not None
        }
        numeric = [float(item.value) for item in observations if item and item.value is not None]
        has_periods = len({item.period for item in observations if item and item.period}) >= 2
        has_movement = len({round(value, 12) for value in numeric}) >= 2
        if len(contexts) >= 2 and (not has_periods or has_movement):
            output.append(plan)
    return output


def _chart_findings(charts: list[ChartPlan], index: DocumentIndex) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    seen: set[str] = set()
    for chart in charts:
        values = [index.get(identifier) for identifier in chart.observation_ids]
        values = [item for item in values if item and item.value is not None and is_meaningful_metric(item)]
        keys = {metric_key(item) for item in values}
        if len(keys) != 1 or not values:
            continue
        key = next(iter(keys))
        if key in seen:
            continue
        by_period: dict[str, Observation] = {}
        for item in values:
            if item.period:
                current = by_period.get(item.period)
                if current is None or item.confidence > current.confidence:
                    by_period[item.period] = item
        ordered = sorted(by_period.values(), key=lambda item: period_sort_key(item.period))
        if len(ordered) < 2:
            continue
        first, last = ordered[0], ordered[-1]
        scale, scale_label = _display_scale(ordered, max(abs(float(item.value or 0)) for item in ordered))
        start, end = float(first.value or 0), float(last.value or 0)
        direction = "increased" if end > start else "decreased"
        if start < 0 <= end:
            direction = "moved from negative to positive"
        elif start > 0 >= end:
            direction = "moved from positive to negative"
        label = sanitize_metric_label(display_metric_name(first))
        start_text = _finding_value(first, scale, scale_label)
        end_text = _finding_value(last, scale, scale_label)
        movement = _change_summary(ordered, scale)
        change_text = f" ({movement[0]})" if movement else ""
        narrative = f"{label} {direction} from {start_text} in {first.period} to {end_text} in {last.period}{change_text}."
        output.append({
            "title": label,
            "narrative": narrative,
            "pages": sorted({source.page for item in ordered for source in item.evidence}),
        })
        seen.add(key)
    return output


def _finding_value(item: Observation, scale: float, scale_label: str) -> str:
    value = _format_scaled(float(item.value or 0), scale)
    if item.unit == "percent":
        return f"{value}%"
    prefix = f"{item.currency} " if item.currency else ""
    suffix = f" {scale_label.rstrip('s')}" if scale_label else ""
    return f"{prefix}{value}{suffix}".strip()


def _appendix_observations(result: PipelineResult, charts: list[ChartPlan]) -> list[Observation]:
    index = DocumentIndex(result.observations)
    used_ids = [identifier for plan in charts for identifier in plan.observation_ids]
    selected = [index.get(identifier) for identifier in used_ids]
    pool = [item for item in selected if item is not None and item.value is not None]
    if not pool or len(pool) < 8:
        all_obs = [item for item in result.observations if item is not None and item.value is not None]
        seen_ids = {p.id for p in pool}
        pool = pool + [item for item in all_obs if item.id not in seen_ids]
    unique: dict[str, Observation] = {}
    for item in pool:
        if item.id not in unique:
            unique[item.id] = item
    return sorted(unique.values(), key=lambda item: (display_metric_name(item), period_sort_key(item.period)))


def _display_scale(observations: list[Observation], max_value: float) -> tuple[float, str]:
    units = {item.unit for item in observations if item.unit}
    families = {getattr(item, "unit_family", None) for item in observations}
    if "percent" in units or "percentage" in families or "multiple" in units or "multiple" in families:
        return 1.0, ""
    if max_value >= 1_000_000_000:
        return 1_000_000_000.0, "billions"
    if max_value >= 1_000_000:
        return 1_000_000.0, "millions"
    if max_value >= 10_000:
        return 1_000.0, "thousands"
    return 1.0, ""


def _unit_label(observations: list[Observation], scale_label: str) -> str:
    units = {item.unit for item in observations if item.unit}
    families = {getattr(item, "unit_family", None) for item in observations}
    if "multiple" in units or "multiple" in families:
        return "x"
    if "percent" in units or "percentage" in families:
        return "percent"
    currencies = {item.currency for item in observations if item.currency}
    raw_units = {item.raw_unit for item in observations if item.raw_unit}
    if currencies:
        base = "/".join(sorted(currencies))
        return f"{base} / {scale_label}" if scale_label else base
    if raw_units:
        clean = re.sub(r"\ufffd+", "'", next(iter(raw_units)))
        clean = re.sub(r"(?i)\bRMB\s*'+\s*000\b", "RMB '000", clean)
        return clean
    return scale_label or "units"


def _display_source_unit(item: Observation) -> str:
    semantic = classify_metric(display_metric_name(item), value=item.value, raw_unit=item.raw_unit, unit=item.unit)
    if semantic.is_multiple:
        return "x"
    if semantic.is_percentage:
        return "%"
    value = item.raw_unit or _unit_label([item], "")
    clean = re.sub(r"\ufffd+", "'", value)
    clean = re.sub(r"(?i)\bRMB\s*'+\s*000\b", "RMB '000", clean)
    clean = re.sub(r"(?i)%\s*of\s*rmb", "RMB '000", clean)
    return clean


def _cell_style(cell: Any, *, fill: str, color: str, bold: bool, size: float) -> None:
    from pptx.util import Inches, Pt

    cell.fill.solid()
    cell.fill.fore_color.rgb = _rgb(fill)
    cell.margin_left = cell.margin_right = Inches(0.08)
    cell.margin_top = cell.margin_bottom = Inches(0.04)
    for paragraph in cell.text_frame.paragraphs:
        paragraph.font.name = FONT
        paragraph.font.size = Pt(size)
        paragraph.font.bold = bold
        paragraph.font.color.rgb = _rgb(color)


def _number_slides(presentation: Any) -> None:
    for index, slide in enumerate(presentation.slides, start=1):
        if index == 1:
            continue
        _text(slide, str(index), 11.60, 6.53, 0.60, 0.23, size=9, color=FOURIER_MUTED, align="right")


def _page_ranges(result: PipelineResult) -> str:
    ranges = result.profile.analysis_page_ranges
    return ", ".join(f"{start}-{end}" for start, end in ranges) if ranges else f"1-{result.document.page_count}"


def _summary_text(value: str, maximum: int) -> str:
    clean = " ".join(value.replace("—", "-").replace("–", "-").split())
    if len(clean) <= maximum:
        return clean
    clipped = clean[:maximum].rsplit(" ", 1)[0].rstrip(" ,:;-")
    return f"{clipped}..." if clipped else f"{clean[:maximum]}..."
