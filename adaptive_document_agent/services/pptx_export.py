"""Editable, presentation-ready PowerPoint export for analysis results based on the FOURIER template."""

from __future__ import annotations

from collections import defaultdict
from contextlib import nullcontext
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
    is_days_metric,
    is_financial_statement_metric,
    is_margin_metric,
    sanitize_metric_label,
)
from adaptive_document_agent.document_model.period_semantic_validator import (
    are_periods_comparable,
    classify_period,
    extract_period_basis,
    format_canonical_period,
    format_observation_period,
    format_period_label,
    is_interim_date,
)
from adaptive_document_agent.models import ChartPlan, Observation, PipelineResult, PresentationSlide
from adaptive_document_agent.utils.period_axis import has_complete_period_cadence
from adaptive_document_agent.services.financial_formatter import (
    format_compact_currency,
    normalize_currency_symbol,
    normalize_raw_unit,
    shorten_metric_title,
)
from adaptive_document_agent.services.movement_formatter import FinancialMovementFormatter
from adaptive_document_agent.services.ppt_preflight import PresentationPreflight
from adaptive_document_agent.services.presentation_preflight_report import PreflightQAError, PreflightReport
from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
BUNDLED_TEMPLATE_PATH = PACKAGE_ROOT / "templates" / "FOURIER Light Version Template EN_251217.pptx"
LOCAL_DESKTOP_TEMPLATE_PATH = Path(r"C:\Users\yuanb\Desktop\FOURIER Light Version Template EN_251217.pptx")
DEFAULT_TEMPLATE_PATH = str(BUNDLED_TEMPLATE_PATH if BUNDLED_TEMPLATE_PATH.exists() else LOCAL_DESKTOP_TEMPLATE_PATH)

# One source for generated colours; original template artwork stays intact.
from .fourier_brand import (
    PRIMARY as FOURIER_PURPLE, LIGHT_PURPLE as FOURIER_LIGHT_PURPLE,
    TECH_BLUE as FOURIER_TECH_BLUE, AMBER as FOURIER_AMBER,
    DEEP_BLUE as FOURIER_DEEP_BLUE, CYAN as FOURIER_CYAN,
    TEXT as FOURIER_DARK, MUTED as FOURIER_MUTED,
    SURFACE as FOURIER_BG_CARD, BORDER as FOURIER_BORDER, WHITE,
    CHART_COLORS,
)

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

CHART_PALETTE = CHART_COLORS


def _source_footer(pages: list[int] | set[int] | tuple[int, ...]) -> str:
    """Return the standardized client-facing source provenance footer."""
    normalized = sorted({int(page) for page in pages if int(page) > 0})
    if not normalized:
        return "Source: Document disclosures (page references not available)"
    ranges = []
    start = end = normalized[0]
    for page in normalized[1:]:
        if page == end + 1:
            end = page
        else:
            ranges.append(str(start) if start == end else f"{start}-{end}")
            start = end = page
    ranges.append(str(start) if start == end else f"{start}-{end}")
    return f"Source: Document disclosures (p. {', '.join(ranges)})"


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


def build_presentation(result: PipelineResult, template_path: str | Path | None = None, *, artwork: bytes | None = None,
                       source_pdf: bytes | None = None, preflight_report: PreflightReport | None = None) -> bytes:
    """Return an editable, presentation-ready PowerPoint based on the FOURIER Light Version Template."""
    presentation = _compose_presentation(result, template_path, artwork=artwork, source_pdf=source_pdf)
    from .requested_tables import verify_requested_tables
    from .summary_export import verify_summary_export
    verify_summary_export(presentation, result)
    preflight = PresentationPreflight(presentation)
    report = preflight_report if preflight_report is not None else PreflightReport()
    report.issues = list(preflight.validate_and_sanitize())
    report.completed = True
    if report.errors:
        raise PreflightQAError(report)
    verify_requested_tables(presentation, result)
    from .slide_compositor import validate_composed_geometry
    validate_composed_geometry(presentation)
    from .presentation_brand_qa import validate_generated_brand
    validate_generated_brand(presentation)
    stream = io.BytesIO()
    presentation.save(stream)
    return stream.getvalue()


def presentation_for_copy(result: PipelineResult):
    """Private display-copy inventory; never an export or a validation verdict.

    Source tables are literal and do not need translating. Their layout or an
    unrelated export preflight must not prevent preparation of Chinese prose.
    The normal build still runs every evidence, table and export gate.
    """
    draft = result.model_copy(deep=True)
    draft.profile.report_requirements.copy_translations = {}
    presentation = _compose_presentation(draft, source_tables=False, validate_plan=False)
    from .requested_tables import requested_table_catalog
    if requested_table_catalog(draft):
        _base_slide(presentation, 'Data Index: Source tables', '')
    return presentation


def _compose_presentation(result, template_path=None, *, artwork=None, source_pdf=None,
                          source_tables=True, validate_plan=True):
    """Share native composition between validated exports and private copy inventory."""
    try:
        from pptx import Presentation
    except ImportError as exc:  # pragma: no cover - deployment configuration failure
        raise RuntimeError("PowerPoint export requires python-pptx.") from exc

    from .source_scope_completeness import prepare_cached_source_scopes
    prepare_cached_source_scopes(result)
    from .presentation_claim_evidence import prepare_presentation_claims
    prepare_presentation_claims(result)
    resolved_path = _resolve_template_path(template_path)
    from .presentation_artwork import validate_artwork
    artwork = validate_artwork(artwork)
    try:
        presentation = Presentation(str(resolved_path))
    except Exception as exc:
        raise ValueError(f"Failed to load PowerPoint template at '{resolved_path}': {exc}") from exc

    presentation._ada_artwork = artwork
    presentation._ada_source_visual = None
    if source_pdf is not None:
        from .presentation_source_visual import select_company_source_visual
        presentation._ada_source_visual = select_company_source_visual(source_pdf, result)
    # Remove template sample slides while retaining master and layouts
    for sld_id in list(presentation.slides._sldIdLst):
        rId = sld_id.rId
        presentation.part.drop_rel(rId)
        del presentation.slides._sldIdLst[presentation.slides._sldIdLst.index(sld_id)]

    from .presentation_style import deck_color_map
    from .composition_data import uses_composition_data, composition_data
    color_keys = []
    color_groups = []
    color_index = DocumentIndex(result.observations)
    for chart in result.charts:
        values = [color_index.get(oid) for oid in chart.observation_ids if color_index.get(oid)]
        if uses_composition_data(chart):
            group = composition_data(chart, values,
                [color_index.get(oid) for oid in chart.total_observation_ids if color_index.get(oid)]).categories
        else:
            rows = _series_rows(chart, values)
            group = [row[0] if chart.chart_type == "pie" else row[1] for row in rows]
        color_keys.extend(group)
        color_groups.append(group)
    presentation._ada_colors = deck_color_map(color_keys, groups=color_groups)

    if result.presentation_plan:
        if validate_plan:
            PresentationPlanValidator().validate(result.presentation_plan, result)
        _build_planned_presentation(presentation, result)
    else:
        _build_legacy_presentation(presentation, result)

    from .presentation_sparse_pages import fold_sparse_text_pages
    fold_sparse_text_pages(presentation, result)
    from .requested_tables import render_requested_tables, verify_requested_tables
    if source_tables:
        render_requested_tables(presentation, result)
    _add_thank_you_slide(presentation)

    _number_slides(presentation)
    from .report_language import apply_report_language
    apply_report_language(presentation, result)
    return presentation


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
    presentation_charts = usable_charts
    chart_groups = _group_chart_plans(presentation_charts, index)

    # Standard order: 1. Cover, 2. Contents, 3. Overview, 4. Analysis at a glance, 5. Findings
    _add_cover(presentation, result)
    _add_contents(presentation, result, chart_groups)
    if result.executive_brief or result.profile.document_summary.strip() or getattr(presentation, "_ada_source_visual", None):
        _add_document_overview(presentation, result)
    _add_findings_slide(presentation, result, presentation_charts, index)
    if chart_groups:
        _add_section_divider(presentation, "Thematic analysis", "Connected measures, periods and source evidence")
    from .slide_compositor import render_composed_slide
    for ordinal, group in enumerate(chart_groups):
        safe_charts = []
        for chart in group:
            values = [index.get(oid) for oid in chart.observation_ids if index.get(oid)]
            safe_charts.append(chart.model_copy(update={"title": _presentation_chart_title(chart.title, values)}))
        findings = _chart_findings(group, index)
        title = safe_charts[0].title if len(safe_charts) == 1 else " / ".join(c.title for c in safe_charts)
        # A long multi-chart heading needs separate pages, not a clipped label.
        groups_to_render = [[c] for c in safe_charts] if len(title) > 110 else [safe_charts]
        for part, selected in enumerate(groups_to_render):
            selected_findings = findings if len(groups_to_render) == 1 else _chart_findings(selected, index)
            render_composed_slide(presentation, PresentationSlide(
                id=f"fallback_{ordinal}_{part}", slide_type="analysis",
                title=selected[0].title if len(selected) == 1 else title,
                chart_ids=[c.id for c in selected],
                bullets=[str(f["narrative"]) for f in selected_findings],
                layout="chart_plus_commentary" if len(selected) == 1 else "two_up",
                source_pages=sorted({p for c in selected for p in c.source_pages})), selected, result, index)
    if not usable_charts:
        _add_no_chart_slide(presentation, result)
    _add_quality_slide(presentation, result)
    _add_section_divider(presentation, "Evidence appendix", "The retained values behind the charts")
    _add_evidence_overview(presentation, result)
    _add_evidence_table_slides(presentation, result, presentation_charts)


def _is_cramped_cluster_render(charts: list[ChartPlan], index: DocumentIndex) -> bool:
    for chart in charts:
        obs = [index.get(oid) for oid in chart.observation_ids if index.get(oid)]
        series_names = {
            item.dimensions.get("series") or item.dimensions.get("breakdown") or item.entity
            for item in obs
            if item
        }
        series_names.discard(None)
        if len(series_names) > 1 or len(chart.title) > 32:
            return True
    return False


def _build_planned_presentation(presentation: Any, result: PipelineResult) -> None:
    """Render the validated AI narrative while keeping all evidence deterministic."""
    plan = result.presentation_plan
    if plan is None:  # pragma: no cover - guarded by caller
        return
    index = DocumentIndex(result.observations)
    chart_by_id = {item.id: item for item in _usable_charts(result)}
    from .presentation_key_figures import select_key_figures
    key_figures = select_key_figures(result, list(chart_by_id.values()))
    from .presentation_ratio_definitions import ratio_definitions
    source_ratio_definitions = ratio_definitions(result)
    presentation._ada_ratio_definitions = source_ratio_definitions
    from .presentation_share_claims import source_total_denominators
    presentation._ada_denominators = source_total_denominators(result)
    from .presentation_display_plan import display_slides
    physical_slides = display_slides(plan, chart_by_id, index)
    from .presentation_export_trace import record_section, clear_trace
    clear_trace(result)
    from .presentation_value_chain import can_render_value_chain
    value_chain = can_render_value_chain(plan.company, presentation.slide_width.inches)
    slides_by_type = {slide.slide_type: slide for slide in plan.slides}
    from .presentation_brief import omit_redundant_summary
    summary = slides_by_type["executive_summary"]
    use_editorial_brief = result.executive_brief is not None or any(
        issue.code == 'executive_brief_unavailable' for issue in result.validation_warnings)
    omit_summary = not use_editorial_brief and omit_redundant_summary(plan, summary)

    # Standard order: 1. Cover, 2. Contents, 3. Company at a Glance, 4. Executive Summary
    cover = slides_by_type["cover"]
    _add_cover(presentation, result, title=cover.title, purpose=cover.message)
    contents_slides = [slide for slide in plan.slides
                       if not (omit_summary and slide.slide_type == "executive_summary")]
    if result.executive_brief is not None:
        from .presentation_closing import editorial_closing_items
        has_review_status = bool(editorial_closing_items(result))
        contents_slides = [s.model_copy(update={'section_title': 'Review status', 'title': 'Review status'})
                          if s.slide_type == 'risks' else s for s in contents_slides
                          if s.slide_type != 'risks' or has_review_status]
    from .presentation_scope import scope_items
    if not scope_items(result):
        contents_slides = [s for s in contents_slides if s.slide_type != "data_quality"]
    if plan.company.summary_review:
        contents_slides = [entry.model_copy(update={'section_title': page.title, 'title': page.title})
                          for entry in contents_slides for page in
                          (plan.company.summary_pages if entry.slide_type == 'company_overview' else [entry])]
    elif plan.company.summary_overview and plan.company.summary_business:
        company_index = next((i for i, s in enumerate(contents_slides) if s.slide_type == "company_overview"), None)
        if company_index is not None:
            contents_slides.insert(company_index + 1, contents_slides[company_index].model_copy(update={
                "section_title": plan.company.summary_business.title,
            }))
    elif (not plan.company.summary_overview and not plan.company.summary_business
          and any(issue.code == 'company_introduction_unavailable' for issue in result.validation_warnings)):
        contents_slides = [s for s in contents_slides if s.slide_type != 'company_overview']
    from .presentation_labels import composition_heading
    from .composition_data import uses_composition_data
    scoped_contents = []
    for entry in contents_slides:
        requests = _planned_chart_requests(entry)
        if entry.slide_type == "analysis" and len(requests) == 1:
            chart = chart_by_id.get(requests[0][0])
            if chart is not None and uses_composition_data(chart):
                heading = composition_heading(entry.section_title or entry.title, chart,
                    [index.get(oid) for oid in chart.observation_ids if index.get(oid)],
                    [index.get(oid) for oid in chart.total_observation_ids if index.get(oid)])
                entry = entry.model_copy(update={"section_title": heading})
        scoped_contents.append(entry)
    _add_planned_contents(presentation, scoped_contents, include_key_figures=bool(key_figures),
                          include_value_chain=value_chain)
    company_start = len(presentation.slides)
    with (record_section(presentation, slides_by_type['company_overview'], result)
          if result.profile.report_requirements else nullcontext()):
        _add_company_at_a_glance(presentation, result, slides_by_type["company_overview"])
    for slide in list(presentation.slides)[company_start:]:
        slide._ada_section_label = getattr(slide, '_ada_section_label', None) or (
            slides_by_type["company_overview"].section_title or 'Company Overview')
    if value_chain:
        from .presentation_value_chain import render_value_chain
        render_value_chain(presentation, plan.company)
    if omit_summary:
        presentation.slides[-1].notes_slide.notes_text_frame.text += (
            "\n\nOmitted duplicate summary; original copy and evidence references:\n"
            + summary.model_dump_json(indent=2)
        )
    else:
        summary_start = len(presentation.slides)
        with (record_section(presentation, summary, result)
              if result.profile.report_requirements else nullcontext()):
            _add_planned_summary(presentation, result, summary, index)
        for slide in list(presentation.slides)[summary_start:]:
            slide._ada_section_label = summary.section_title or 'Executive Summary'
    from .presentation_identity import presentation_quality_notes
    quality_notes = presentation_quality_notes(result)
    if quality_notes:
        notes = presentation.slides[-1].notes_slide.notes_text_frame
        notes.text += "\n\nSource scope and data-quality notes:\n" + "\n".join(quality_notes)
    if key_figures:
        from .presentation_key_figures import render_key_figures
        render_key_figures(presentation, key_figures)

    rendered_charts: list[ChartPlan] = []
    ordinal = 0
    for slide_plan in physical_slides[3:]:
        with record_section(presentation, slide_plan, result):
            if slide_plan.slide_type == "analysis":
                horizon = [block for block in slide_plan.visual_blocks if block.role == "horizon"]
                if horizon:
                    from .presentation_horizon import render_horizon
                    render_horizon(presentation, slide_plan, horizon[0], index, result.document)
                    ordinal += 1
                    continue
                matrix = [block for block in slide_plan.visual_blocks if block.role == "matrix"]
                if matrix:
                    from .presentation_matrix import render_matrix
                    from .presentation_context_notes import slide_context_notes
                    render_matrix(presentation, slide_plan, matrix[0], index,
                                  context_notes=slide_context_notes(result, slide_plan, [], index), result=result)
                    ordinal += 1
                    continue
                waterfall = [block for block in slide_plan.visual_blocks if block.role == "waterfall"]
                if waterfall:
                    from .presentation_waterfall import render_waterfall
                    render_waterfall(presentation, slide_plan, waterfall[0], index)
                    ordinal += 1
                    continue
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
                # A coherent single metric deserves a full analytical page even
                # when the planner supplied only observation IDs and a table layout.
                from .single_metric_analysis import single_metric_analysis
                from .single_metric_renderer import add_single_metric_slide
                linked = {o.id: o for o in _planned_observations(slide_plan, index)}
                for chart in charts:
                    linked.update({oid: index.get(oid) for oid in chart.observation_ids if index.get(oid)})
                if re.search(r"(?i)evidence.backed comparison|retained reported values|selected observations", slide_plan.message):
                    # Mechanical fallback copy carries no supported takeaway. Name
                    # the actual plotted subjects instead of an over-broad heading.
                    from .presentation_labels import qualified_metric_name
                    labels = list(dict.fromkeys(qualified_metric_name(o) for o in linked.values()))
                    evidence_title = " and ".join(labels)
                    slide_plan = slide_plan.model_copy(update={
                        "title": evidence_title if 0 < len(evidence_title) <= 150 else "Reported measures",
                        "message": ""})
                single = single_metric_analysis(list(linked.values())) if len(charts) <= 1 else None
                legacy_overview = plan.planning_origin == "legacy" and slide_plan.layout == "data_overview"
                use_hero = not slide_plan.theme_id and (slide_plan.layout in {"auto", "single", "single_metric_hero"} or legacy_overview)
                if single and use_hero and not any(_is_positive_topic_mismatch(o, slide_plan) for o in single.observations):
                    explicit_composition = bool(slide_plan.bullets or slide_plan.insight_ids or any(
                        b.role in {"kpi", "table", "commentary"} or b.insight_ids for b in slide_plan.visual_blocks))
                    if explicit_composition and charts:
                        from .slide_compositor import render_composed_slide
                        render_composed_slide(presentation, slide_plan, charts, result, index)
                        rendered_charts.extend(charts)
                        ordinal += 1
                        continue
                    hero = charts[0] if charts else ChartPlan(
                        id=f"hero_{slide_plan.id}", title=display_metric_name(single.observations[0]),
                        chart_type="line", question=slide_plan.message,
                        observation_ids=[o.id for o in single.observations],
                        source_pages=sorted({e.page for o in single.observations for e in o.evidence}),
                    )
                    series_ids = {item.id for item in single.observations}
                    definitions = [definition for definition in source_ratio_definitions
                                   if series_ids <= set(definition["observation_ids"])]
                    from .presentation_source_context import source_table_context
                    add_single_metric_slide(presentation, hero, single, title=slide_plan.title,
                                            narrative=slide_plan.message,
                                            definition=definitions[0] if len(definitions) == 1 else None,
                                            source_context=source_table_context(single.observations, result.document)
                                            if single.is_percentage and not definitions else "")
                    rendered_charts.append(hero)
                    ordinal += 1
                    continue
                if charts or any(b.role in {"kpi", "table"} and b.observation_ids for b in slide_plan.visual_blocks):
                    from .slide_compositor import render_composed_slide
                    render_composed_slide(presentation, slide_plan, charts, result, index)
                    rendered_charts.extend(charts)
                    ordinal += 1
                    continue
                else:
                    observations = _planned_observations(slide_plan, index)
                    if not observations:
                        insight_by_id = {item.id: item for item in result.insights}
                        candidate_obs = []
                        for iid in slide_plan.insight_ids:
                            ins = insight_by_id.get(iid)
                            if ins and ins.metric:
                                candidate_obs.extend([o for o in index.for_metric(ins.metric) if o.value is not None])
                        if len(candidate_obs) >= 2:
                            observations = candidate_obs[:4]

                    if observations:
                        _add_planned_data_slide(presentation, slide_plan, observations)
                    else:
                        continue
            elif slide_plan.slide_type == "risks":
                _add_planned_text_slide(presentation, result, slide_plan)
            elif slide_plan.slide_type == "data_quality":
                from .presentation_scope import scope_items, scope_audit_notes
                from .presentation_summary import render_complete_summary
                limits = scope_items(result)
                if limits:
                    render_complete_summary(presentation, "Coverage and limits", limits,
                                            notes=scope_audit_notes(result))
                elif len(presentation.slides):
                    presentation.slides[-1].notes_slide.notes_text_frame.text += "\n\n" + scope_audit_notes(result)
                continue
            elif slide_plan.slide_type == "appendix":
                previous_slide_count = len(presentation.slides)
                if rendered_charts or plan.themes:
                    appendix_charts = rendered_charts
                    _add_evidence_table_slides(presentation, result, appendix_charts, title="Data Index")
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
                if quality_notes and len(presentation.slides) > previous_slide_count:
                    notes = presentation.slides[previous_slide_count].notes_slide.notes_text_frame
                    notes.text += "\n\nSource scope and data-quality notes:\n" + "\n".join(quality_notes)


def _planned_chart_requests(slide_plan: PresentationSlide) -> list[tuple[str, str | None]]:
    requests: list[tuple[str, str | None]] = [(identifier, None) for identifier in slide_plan.chart_ids]
    for block in slide_plan.visual_blocks:
        requests.extend((identifier, block.chart_type) for identifier in block.chart_ids)
    output: dict[str, str | None] = {}
    for identifier, chart_type in requests:
        if identifier not in output or chart_type is not None:
            output[identifier] = chart_type
    return list(output.items())[:3]


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


def _add_planned_contents(
    presentation: Any, planned_slides: list[PresentationSlide], *, evidence_in_notes: bool = False,
    include_key_figures: bool = False,
    include_value_chain: bool = False,
) -> None:
    """Use authored section labels, grouping only sections with the same label."""
    entries: list[str] = []
    seen: set[str] = set()
    defaults = {
        "company_overview": "Company Overview",
        "executive_summary": "Executive Summary",
        "analysis": "Analysis",
        "risks": "Key Risks and Watch Items",
        "data_quality": "Coverage and limits",
        "appendix": "Data Index",
    }
    contents_order = planned_slides
    for position, item in enumerate(contents_order):
        if item.slide_type not in defaults:
            continue
        if evidence_in_notes and item.slide_type == "appendix":
            continue
        section_label = item.section_title.strip()
        label = ("Data Index" if item.slide_type == "appendix" else defaults[item.slide_type]
                 if item.slide_type == "data_quality" else section_label
                 or (item.title.strip() or defaults[item.slide_type]
                     if item.slide_type == "analysis" else defaults[item.slide_type]))
        key = label.casefold()
        if key not in seen:
            seen.add(key)
            entries.append(label)
        if (include_value_chain and item.slide_type == 'company_overview'
                and not any(s.slide_type == 'company_overview' for s in contents_order[position + 1:])
                and 'how the business operates' not in seen):
            seen.add('how the business operates')
            entries.append('How the business operates')
        if include_key_figures and item.slide_type == 'executive_summary' and 'key figures' not in seen:
            seen.add('key figures')
            entries.append('Key Figures')

    _render_contents_entries(presentation, entries, "Presentation structure")


def _render_contents_entries(presentation: Any, entries: list[str], subtitle: str) -> None:
    """Keep the agenda on one page, with complete authored labels in notes."""
    from .presentation_contents import contents_layout

    top = 1.50
    capacity = presentation.slide_height.inches - 1.0 - top
    columns, column_width, font_size, line_spacing = contents_layout(
        entries, presentation.slide_width.inches, capacity)
    slide = _base_slide(presentation, "Contents", subtitle)
    slide.notes_slide.notes_text_frame.text += "\n\nComplete agenda:\n" + "\n".join(
        f"{number:02d}. {label}" for number, label in enumerate(entries, 1))
    for column, items in enumerate(columns):
        left, y = .55 + column * (column_width + .30), top
        for number, label, row_h in items:
            _text(slide, f"{number:02d}", left, y + .02, .46, row_h - .04,
                  size=font_size, color=FOURIER_PURPLE, bold=True)
            shape = _text(slide, label, left + .60, y + .02, column_width - .60, row_h - .04,
                          size=font_size, color=FOURIER_DARK)
            for paragraph in shape.text_frame.paragraphs:
                paragraph.line_spacing = Pt(line_spacing)
                paragraph.space_before = paragraph.space_after = Pt(0)
            shape.name = f"contents:entry:{number}"
            y += row_h + .08


def _presentation_company_identity(result: PipelineResult) -> tuple[str, list[int]]:
    """Reuse a resolved identity and its retained citations, without inferring one."""
    from .company_extractor import is_company_identity_resolved

    company = result.presentation_plan.company if result.presentation_plan else None
    if not is_company_identity_resolved(company):
        return "", []
    pages = company.field_source_pages.get("name") or company.source_pages
    return " ".join(company.name.split()), sorted(set(pages))


def _add_company_at_a_glance(presentation: Any, result: PipelineResult, slide_plan: PresentationSlide) -> None:
    plan = result.presentation_plan
    if plan is None:  # pragma: no cover - guarded by caller
        return

    if plan.company.summary_review is not None:
        from .company_summary import validate_summary
        from .presentation_brief import BriefItem, render_profile
        errors = validate_summary(plan.company, result)
        if errors:
            raise ValueError('Invalid complete Summary introduction: ' + '; '.join(errors))
        if not plan.company.summary_pages and len(presentation.slides):
            presentation.slides[-1].notes_slide.notes_text_frame.text += (
                '\n\nComplete Summary reading and omission decisions:\n'
                + plan.company.summary_review.model_dump_json(indent=2))
        for index, page in enumerate(plan.company.summary_pages):
            items = [BriefItem(item.label, item.text, item.source_pages) for item in page.items]
            notes = page.model_dump_json(indent=2)
            if index == 0:
                notes += '\n\nComplete Summary reading and decisions:\n' + (
                    plan.company.summary_review.model_dump_json(indent=2))
            source_visual = getattr(presentation, '_ada_source_visual', None)
            if index == 0 and source_visual:
                from .presentation_source_visual import render_profile_with_source
                rendered = render_profile_with_source(presentation, page.title, items, source_visual, notes=notes)
            else:
                rendered = render_profile(presentation, page.title, items, notes=notes)
            from .summary_export import bind_summary_pages
            bind_summary_pages(rendered, page)
            for slide in rendered:
                slide._ada_section_label = page.title
        # A fully read Summary with justified omissions needs no placeholder.
        return

    available_summaries = [summary for summary in
                           (plan.company.summary_overview, plan.company.summary_business) if summary]
    if (not available_summaries
            and any(issue.code == "company_introduction_unavailable" for issue in result.validation_warnings)):
        if len(presentation.slides):
            presentation.slides[-1].notes_slide.notes_text_frame.text += (
                '\n\nCompany introduction omitted: source verification failed. '
                'See company_introduction_unavailable and company_introduction_summary_audit in analysis diagnostics.')
        return

    if available_summaries:
        from .company_summary import validate_summary
        from .presentation_brief import BriefItem, render_profile

        errors = validate_summary(plan.company, result)
        if errors:
            raise ValueError("Invalid company Summary introduction: " + "; ".join(errors))
        company_name, identity_pages = _presentation_company_identity(result)
        for page_index, summary in enumerate(available_summaries):
            items = [BriefItem(item.label, item.text, item.source_pages) for item in summary.items]
            title = summary.title
            notes = summary.model_dump_json(indent=2)
            if page_index == 0 and company_name:
                title = company_name
                first = items[0]
                items[0] = BriefItem(first.title, first.text, sorted(set(first.pages) | set(identity_pages)))
                notes += "\n\nCompany identity: " + company_name + "\n" + _source_footer(identity_pages)
            source_visual = getattr(presentation, "_ada_source_visual", None)
            if page_index == 0 and source_visual:
                from .presentation_source_visual import render_profile_with_source
                rendered = render_profile_with_source(presentation, title, items, source_visual, notes=notes)
            else:
                rendered = render_profile(presentation, title, items, notes=notes)
            if len(rendered) != 1 and not (page_index == 0 and source_visual):
                raise ValueError("Company Summary copy exceeds its one-page budget; shorten the introduction.")
        return

    from adaptive_document_agent.services.company_extractor import (
        extract_structured_company_fields,
        is_company_identity_resolved,
    )

    company = (plan.company if result.finalization is not None
               else extract_structured_company_fields(plan.company, result))
    if result.finalization is None:
        plan.company = company

    has_company_identity = is_company_identity_resolved(company)

    slide_title = slide_plan.title if has_company_identity else "Document at a Glance"
    artwork = getattr(presentation, "_ada_artwork", None)
    source_visual = getattr(presentation, "_ada_source_visual", None)
    if artwork or source_visual:
        from .presentation_artwork import add_picture_profile
        pages = sorted(set(company.source_pages) | set(slide_plan.source_pages)
                       | {p for values in company.field_source_pages.values() for p in values}
                       | {p for fact in company.key_facts for p in fact.source_pages})
        if source_visual:
            pages = sorted(set(pages) | {source_visual.page})
        add_picture_profile(presentation, company, slide_title, pages,
                            source_visual.payload if source_visual else artwork,
                            source_page=source_visual.page if source_visual else None)
        return
    from .presentation_brief import BriefItem, overview_items, render_profile
    # Keep long qualified ranking claims intact in notes. Truncating the basis,
    # geography or attribution to make a one-page card would change meaning.
    visible_market_position = company.market_position if len(company.market_position) <= 160 else ""
    groups = [
        (company.name if has_company_identity else "Document overview",
         [("Profile", company.one_line_description, "one_line_description"),
          ("Industry", company.industry, "industry"),
          ("Headquarters", company.headquarters, "headquarters"),
          ("Reporting currency", company.reporting_currency, "reporting_currency"),
          ("Track record", company.track_record_period, "track_record_period")]),
        ("Business and products",
         [("Business model", company.business_model, "business_model"),
          ("Products", ", ".join(company.products), "products"),
          ("Segments", ", ".join(company.segments), "segments")]),
        ("Applications and customers",
         [("Applications", ", ".join(company.application_areas), "application_areas"),
          ("Customers", ", ".join(company.customer_types), "customer_types")]),
        ("Markets and listing" if company.geographies or visible_market_position else "Listing details",
         [("Markets", ", ".join(company.geographies), "geographies"),
          ("Market position", visible_market_position, "market_position"),
          ("Exchange", company.listing_market, "listing_market"),
          ("Stock code", company.stock_code, "stock_code"),
          ("Offering", company.offering_type, "offering_type"),
          ("Listing details", ", ".join(fact for fact in company.listing_facts
           if not re.match(r"(?i)^(?:stock\s*code|exchange|offering\s*type|track\s*record)\s*:", fact)), "listing_facts")]),
    ]
    items = []
    for heading, fields in groups:
        populated = [(label, value, key) for label, value, key in fields if value]
        if populated:
            pages = sorted({p for _, _, key in populated for p in company.field_source_pages.get(key, [])}
                           | set(company.field_source_pages.get("name", []) if heading == company.name else []))
            items.append(BriefItem(heading, ". ".join(f"{label}: {value}" for label, value, _ in populated),
                                   pages or company.source_pages))
    if not items:
        items, _ = overview_items(result.profile)
    elif has_company_identity and items[0].title != company.name:
        items.insert(0, BriefItem("Company", company.name, company.field_source_pages.get("name", [])))
    if not has_company_identity and items:
        first = items[0]
        items[0] = BriefItem(first.title, "Issuer name not identified in supplied pages. " + first.text, first.pages)
    # Full fields and source context remain available without clipping the
    # visible labels or constructing large, mostly empty cards.
    notes = company.model_dump_json(indent=2) + "\n\n" + result.profile.document_summary
    visible_copy = " ".join(item.text for item in items).casefold()
    represented_fact_labels = {
        "industry": bool(company.industry),
        "headquarters": bool(company.headquarters),
        "reporting currency": bool(company.reporting_currency),
        "track record period": bool(company.track_record_period),
        "main products services": bool(company.products or company.segments),
        "products services": bool(company.products or company.segments),
        "applications": bool(company.application_areas),
        "use cases": bool(company.application_areas),
        "business model": bool(company.business_model),
        "customers": bool(company.customer_types),
        "customer types": bool(company.customer_types),
        "main geographic market": bool(company.geographies),
        "geographic markets": bool(company.geographies),
        "market position": bool(company.market_position),
        "listing market": bool(company.listing_market),
        "stock code": bool(company.stock_code),
        "offering type": bool(company.offering_type),
    }
    for fact in company.key_facts:
        normal_label = re.sub(r"[^a-z0-9]+", " ", fact.label.casefold()).strip()
        already_represented = represented_fact_labels.get(normal_label, False)
        if (fact.value.strip() and fact.source_pages and not already_represented
                and fact.value.casefold() not in visible_copy):
            items.append(BriefItem(fact.label, fact.value, fact.source_pages))
            visible_copy += " " + fact.value.casefold()
    render_profile(presentation, "Company at a Glance" if has_company_identity else "Document at a Glance",
                 items, notes=notes)


def _is_calc_artifact(text: str) -> bool:
    from .presentation_brief import is_technical_copy
    if is_technical_copy(text):
        return True
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
    from adaptive_document_agent.services.language_qa import clean_presentation_text
    return clean_presentation_text(text)


def _add_planned_summary(
    presentation: Any,
    result: PipelineResult,
    slide_plan: PresentationSlide,
    index: DocumentIndex,
) -> None:
    from .executive_brief import display_brief
    brief_title, selected_brief = display_brief(result)
    if selected_brief and (result.executive_brief is not None or any(
            issue.code == 'executive_brief_unavailable' for issue in result.validation_warnings)):
        from .presentation_summary import render_complete_summary
        notes = result.executive_brief.model_dump_json(indent=2) if result.executive_brief else ''
        render_complete_summary(presentation, brief_title, selected_brief,
                                notes=notes, single_column=True)
        return
    if _planned_chart_requests(slide_plan) or any(b.role in {"kpi", "table"} and b.observation_ids for b in slide_plan.visual_blocks):
        from .slide_compositor import render_composed_slide
        by_id = {c.id: c for c in _usable_charts(result)}
        charts = [by_id[cid].model_copy(update={"chart_type": kind or by_id[cid].chart_type})
                  for cid, kind in _planned_chart_requests(slide_plan) if cid in by_id]
        render_composed_slide(presentation, slide_plan, charts, result, index)
        return
    insight_by_id = {item.id: item for item in result.insights}
    raw_findings = [
        (insight_by_id[identifier].title, insight_by_id[identifier].narrative)
        for identifier in slide_plan.insight_ids
        if identifier in insight_by_id
    ]
    # Recover each selected finding independently. One usable prose item must
    # not prevent recovery of other important, technically worded findings.
    by_task = {item.task_id: item for item in result.analysis_results}
    recovered = []
    for identifier in slide_plan.insight_ids:
        insight = insight_by_id.get(identifier)
        if insight is None:
            continue
        if _is_calc_artifact(insight.title) or _is_calc_artifact(insight.narrative):
            ids = list(dict.fromkeys(oid for task in insight.result_ids if task in by_task
                                     for oid in by_task[task].input_observation_ids))
            candidates = _chart_findings([ChartPlan(id="summary_" + identifier,
                title=insight.title, question="", chart_type="line", observation_ids=ids)], index) if ids else []
            recovered.extend(candidates[:1])
        elif insight.evidence:
            linked = [index.get(oid) for task in insight.result_ids if task in by_task
                      for oid in by_task[task].input_observation_ids if index.get(oid)]
            labels = {display_metric_name(o) for o in linked}
            recovered.append({"title": _sanitize_investor_narrative(insight.title),
                "narrative": _sanitize_investor_narrative(insight.narrative),
                "short_title": next(iter(labels)) if len(labels) == 1 else "",
                "pages": sorted({e.page for e in insight.evidence})})
    findings = [(str(f["title"]), str(f["narrative"])) for f in recovered]
    if slide_plan.bullets:
        bullet_findings = [
            ("", _sanitize_investor_narrative(bullet))
            for bullet in slide_plan.bullets
            if bullet.strip() and not _is_calc_artifact(bullet)
        ]
        if not findings:
            findings = bullet_findings
        else:
            findings = [*findings, *bullet_findings]
    fallback_pages: set[int] = set()
    if not findings:
        fallback_findings = _chart_findings(_usable_charts(result), index)
        findings = [
            (str(item["title"]), str(item["narrative"]))
            for item in fallback_findings
            if not _is_calc_artifact(str(item["title"])) and not _is_calc_artifact(str(item["narrative"]))
        ]
        fallback_pages = {p for item in fallback_findings for p in item.get("pages", [])}
    from .presentation_editorial import distinct_findings
    from .presentation_brief import BriefItem
    from .presentation_summary import render_complete_summary
    if (result.presentation_plan and result.presentation_plan.planning_origin in {"topic_recovery", "topic_compilation"}
            and slide_plan.bullets
            and all(not _is_calc_artifact(b) for b in slide_plan.bullets)):
        # Render the validated/repaired summary, not the pre-repair insight
        # narrative. Full analytical prose stays in notes and subsequent pages.
        scoped = len(slide_plan.bullet_observation_ids) == len(slide_plan.bullets)
        items = [BriefItem("", _sanitize_investor_narrative(bullet),
                           sorted({e.page for oid in slide_plan.bullet_observation_ids[position]
                                   if index.get(oid) for e in index.get(oid).evidence})
                           if scoped else slide_plan.source_pages)
                 for position, bullet in enumerate(slide_plan.bullets)]
        notes = "\n\n".join(f"{title}\n{body}" for title, body in raw_findings)
        render_complete_summary(presentation, slide_plan.title, items, notes=notes)
        return
    # Keep every selected finding visible; overflow continues on another page.
    pages = sorted(set(slide_plan.source_pages) | fallback_pages | {
        e.page for identifier in slide_plan.insight_ids if identifier in insight_by_id
        for e in insight_by_id[identifier].evidence})
    notes = "\n\n".join(f"{t}\n{n}" for t, n in raw_findings)
    notes += "\n\n" + "\n".join(slide_plan.bullets)
    finding_key = lambda title, body: (" ".join(title.casefold().split()), " ".join(body.casefold().split()))
    finding_pages, short_titles = {}, {}
    for finding in recovered:
        key = finding_key(str(finding["title"]), str(finding["narrative"]))
        finding_pages.setdefault(key, set()).update(finding["pages"])
        short_titles.setdefault(key, str(finding.get("short_title", "")))
    items = [BriefItem(label, narrative, sorted(finding_pages.get(finding_key(label, narrative), pages)),
                       short_titles.get(finding_key(label, narrative), ""))
             for label, narrative in distinct_findings(findings)]
    render_complete_summary(presentation, slide_plan.title, items, notes=notes)


from adaptive_document_agent.document_model.topic_matcher import (
    extract_topic_tokens as _extract_topic_tokens,
    metrics_match_topic as _metrics_match_topic,
    filter_observations_by_slide_topic as _filter_observations_by_slide_topic,
    get_slide_context as _get_slide_context,
    is_positive_topic_mismatch as _is_positive_topic_mismatch,
)


def _add_planned_data_slide(
    presentation: Any,
    slide_plan: PresentationSlide,
    observations: list[Observation],
) -> None:
    slide = _base_slide(presentation, slide_plan.title, slide_plan.message)
    content_top, content_h = _content_zone(slide)

    filtered_observations = _filter_observations_by_slide_topic(
        observations, slide_plan.title, slide_context=_get_slide_context(slide_plan)
    )

    # Check if observations represent a multi-period series for comparison
    periods_set = {obs.period for obs in filtered_observations if obs.period}
    metrics_by_name: dict[str, list[Observation]] = {}
    for obs in filtered_observations:
        m_name = display_metric_name(obs)
        metrics_by_name.setdefault(m_name, []).append(obs)

    is_multi_period = len(periods_set) >= 2 and any(len(obs_list) >= 2 for obs_list in metrics_by_name.values())

    if is_multi_period:
        _render_data_comparison_table(slide, slide_plan, metrics_by_name, content_top, content_h)
        return

    selected = filtered_observations[:4]
    card_count = len(selected)
    card_h = min(1.30, (content_h - 0.20) / max(card_count, 1)) if card_count <= 2 else min(1.10, (content_h - 0.15) / 2)

    for index, item in enumerate(selected):
        if card_count <= 2:
            left = 0.45 + index * 5.95
            y = content_top + 0.40
            w = 5.75
        else:
            column = index % 2
            row = index // 2
            left = 0.45 + column * 5.95
            y = content_top + row * (card_h + 0.20)
            w = 5.75
        pages = ", ".join(map(str, sorted({source.page for source in item.evidence})))

        semantic = classify_metric(
            display_metric_name(item),
            value=item.value,
            raw_unit=item.raw_unit,
            unit=item.unit,
        )
        metric_title = semantic.short_display_name or semantic.clean_name

        value_str = format_metric_display_value(
            item.raw_value,
            item.value,
            semantic,
            raw_unit=_display_source_unit(item),
            currency=item.currency,
        )

        is_bs = any(term in metric_title.casefold() for term in ("liabilit", "cash", "balance", "receiv", "payab", "inventor", "asset", "equity", "deficit"))
        period_str = format_observation_period(item) or format_period_label(item.period, is_balance_sheet=is_bs)

        _panel(slide, left, y, w, card_h, fill=FOURIER_BG_CARD)
        _text(slide, _summary_text(metric_title, 48), left + 0.20, y + 0.12, 3.60, 0.32, size=12, color=FOURIER_MUTED, bold=True)
        _text(slide, _summary_text(value_str, 42), left + 0.20, y + 0.46, 3.60, 0.45, size=19, color=FOURIER_DARK, bold=True)
        _text(slide, period_str or item.entity or "Reported value", left + 3.80, y + 0.50, 1.75, 0.30, size=11, color=FOURIER_TECH_BLUE, bold=True, align="right")
        if pages:
            _text(slide, f"p. {pages}", left + 4.30, y + 0.12, 1.25, 0.24, size=9, color=FOURIER_MUTED, align="right")


def _render_data_comparison_table(
    slide: Any,
    slide_plan: PresentationSlide,
    metrics_by_name: dict[str, list[Observation]],
    content_top: float,
    content_h: float,
) -> None:
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.util import Inches
    from adaptive_document_agent.document_model import period_sort_key
    from adaptive_document_agent.services.language_qa import clean_metric_label

    all_periods = sorted(
        {obs.period for obs_list in metrics_by_name.values() for obs in obs_list if obs.period},
        key=period_sort_key,
    )
    # Build a period-to-best-obs lookup for accurate is_balance_sheet detection
    _period_obs_lookup: dict[str, Observation] = {}
    for obs_list in metrics_by_name.values():
        for obs in obs_list:
            if obs.period and obs.period not in _period_obs_lookup:
                _period_obs_lookup[obs.period] = obs
    headers = ["Metric"] + [
        (format_observation_period(_period_obs_lookup[p]) if p in _period_obs_lookup
         else format_canonical_period(p)) or p
        for p in all_periods
    ]
    rows: list[tuple[str, list[str]]] = []
    all_pages: set[int] = set()

    for raw_m_name, obs_list in metrics_by_name.items():
        pres_label = clean_metric_label(raw_m_name)
        obs_by_p = {obs.period: obs for obs in obs_list if obs.period}
        vals: list[str] = []
        for p in all_periods:
            obs = obs_by_p.get(p)
            if obs:
                semantic = classify_metric(display_metric_name(obs), value=obs.value, raw_unit=obs.raw_unit, unit=obs.unit)
                val_str = format_metric_display_value(obs.raw_value, obs.value, semantic, raw_unit=_display_source_unit(obs), currency=obs.currency, compact=True)
                vals.append(val_str)
                all_pages.update(s.page for s in obs.evidence if getattr(s, "page", None))
            else:
                vals.append("—")
        rows.append((pres_label, vals))

    num_rows = len(rows) + 1
    num_cols = len(headers)
    table_top = content_top + 0.15
    table_h = min(4.20, num_rows * 0.45)
    table_shape = slide.shapes.add_table(num_rows, num_cols, Inches(0.85), Inches(table_top), Inches(10.90), Inches(table_h))
    table = table_shape.table

    metric_w = max(3.50, 10.90 - (num_cols - 1) * 1.60)
    col_w = (10.90 - metric_w) / max(num_cols - 1, 1)
    table.columns[0].width = Inches(metric_w)
    for c in range(1, num_cols):
        table.columns[c].width = Inches(col_w)

    for c, h in enumerate(headers):
        cell = table.cell(0, c)
        cell.text = h
        _cell_style(cell, fill=FOURIER_PURPLE, color=WHITE, bold=True, size=11.0)
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        if c > 0:
            cell.text_frame.paragraphs[0].alignment = PP_ALIGN.RIGHT

    for r_idx, (m_label, vals) in enumerate(rows, start=1):
        row_fill = WHITE if r_idx % 2 == 0 else FOURIER_BG_CARD
        cell0 = table.cell(r_idx, 0)
        cell0.text = m_label
        _cell_style(cell0, fill=row_fill, color=FOURIER_DARK, bold=True, size=10.5)
        cell0.vertical_anchor = MSO_ANCHOR.MIDDLE
        for c_idx, val in enumerate(vals, start=1):
            cell = table.cell(r_idx, c_idx)
            cell.text = val
            _cell_style(cell, fill=row_fill, color=FOURIER_DARK, bold=False, size=10.5)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.text_frame.paragraphs[0].alignment = PP_ALIGN.RIGHT

    if all_pages:
        _text(slide, _source_footer(all_pages), 0.85, 6.25, 10.90, 0.25, size=9.5, color=FOURIER_MUTED)


def _add_planned_text_slide(presentation: Any, result: PipelineResult, slide_plan: PresentationSlide) -> None:
    if slide_plan.slide_type == "risks":
        from .presentation_closing import render_closing
        render_closing(presentation, result, slide_plan)
        return
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
    if is_risk_or_watch and len(messages) <= 4:
        from .presentation_brief import BriefItem, render_summary
        items = [BriefItem(f"Watch item {number}", _sanitize_investor_narrative(narrative),
                           slide_plan.source_pages)
                 for number, (_, narrative) in enumerate(messages, start=1)
                 if narrative.strip()]
        notes = "Analytical interpretation based on reported movements.\n\n" + "\n\n".join(
            narrative for _, narrative in messages if narrative.strip()
        )
        render_summary(presentation, slide_plan.title, items, notes=notes)
        return
    body = "\n\n".join(f"{label}\n{narrative}" if label else narrative for label, narrative in messages)
    if is_risk_or_watch:
        body = "Analytical interpretation based on reported movements\n\n" + body
    _add_text_pages(presentation, slide_plan.title, body, slide_plan.source_pages, subtitle=slide_plan.message)


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
        _text(slide, _source_footer(source_pages), 0.45, 6.22, 11.70, 0.25, size=9.5, color=FOURIER_MUTED, align="right")


def _add_contents(presentation: Any, result: PipelineResult, groups: list[list[ChartPlan]]) -> None:
    sections: list[str] = []
    if result.profile.document_summary.strip():
        sections.append("Document overview")
    sections.append("Key findings")
    if groups:
        sections.append("Thematic analysis")
    sections.extend(("Data quality and limitations", "Evidence appendix"))
    _render_contents_entries(presentation, sections, "A structured path through the evidence")


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

    cover_title = title or result.report_plan.title or result.profile.overview_title or "Adaptive Document Analysis"
    from .language_qa import clean_presentation_text
    from .slide_compositor import _lines
    clean_title = clean_presentation_text(cover_title)
    clean_purpose = clean_presentation_text(purpose or result.profile.document_purpose or result.profile.document_summary or "Intelligence derived from reported statements")
    original_purpose = clean_purpose
    # A planner may append an analysis scope after a colon. The scope belongs
    # in the contents and body, while the cover needs a readable subject.
    if len(clean_title) > 70 and ":" in clean_title:
        subject = clean_title.split(":", 1)[0].strip()
        if len(subject) >= 15:
            clean_title = subject
            clean_purpose = "Document analysis"

    company_name, identity_pages = _presentation_company_identity(result)
    if company_name and company_name.casefold() not in " ".join(clean_title.casefold().split()):
        # Put the already-resolved subject first. Keep the planner's document
        # topic as the subtitle, and its complete analytical scope in notes.
        clean_purpose, clean_title = clean_title, company_name
    elif company_name and len(_lines(clean_title, 6.65, 36)) > 3:
        # A company name embedded in a long document title still needs the
        # short cover treatment. Preserve the complete planned title in notes.
        clean_purpose = re.sub(re.escape(company_name), '', clean_title, count=1, flags=re.I).strip(' :,-')
        clean_title = company_name

    import json
    note_data = {
        "planned_title": cover_title, "document_purpose": original_purpose,
        "company_identity": {"name": company_name, "source_pages": identity_pages},
    }
    notes = json.dumps(note_data, ensure_ascii=False, indent=2)
    if getattr(presentation, "_ada_artwork", None):
        from .presentation_artwork import add_picture_cover
        slide = add_picture_cover(presentation, clean_title, clean_purpose, presentation._ada_artwork)
        slide.notes_slide.notes_text_frame.text += "\n\n" + notes
        return
    slide = presentation.slides.add_slide(presentation.slide_layouts[0])
    slide.notes_slide.notes_text_frame.text = notes

    # Retain the template's 36 pt cover title; reflow instead of shrinking it.
    title_font_size = 36
    from .text_capacity import balance_title
    clean_title = balance_title(clean_title, 6.65, title_font_size)
    title_h = max(.85, len(_lines(clean_title, 6.65, title_font_size)) * title_font_size / 72 * 1.22 + .15)
    if title_h > 3.1:
        raise ValueError("Cover title exceeds readable capacity; shorten the presentation title.")
    subtitle_top = max(2.80, 1.35 + title_h + .28)
    def subtitle_height(text: str) -> float:
        return max(.95, len(_lines(text, 6.65, 26)) * 26 / 72 * 1.22 + .12)

    purpose_h = subtitle_height(clean_purpose)
    if subtitle_top + purpose_h > 6.15:
        # Preserve the whole qualified statement in notes. A complete context
        # label can replace it on the cover without inventing or truncating a claim.
        note_data["deferred_cover_subtitle"] = clean_purpose
        context = clean_presentation_text(result.profile.document_type or "")
        if (not context or context.casefold() == clean_title.casefold()
                or subtitle_top + subtitle_height(context) > 6.15):
            context = "Document analysis"
        clean_purpose = context
        purpose_h = subtitle_height(clean_purpose)
        note_data["displayed_subtitle"] = clean_purpose
        slide.notes_slide.notes_text_frame.text = json.dumps(note_data, ensure_ascii=False, indent=2)

    ph16 = None
    ph15 = None
    for ph in slide.placeholders:
        if ph.placeholder_format.idx == 16:
            ph16 = ph
            ph.text = clean_title
            ph.left = Inches(0.30)
            ph.top = Inches(1.35)
            ph.width = Inches(6.85)
            ph.height = Inches(title_h)
            ph.text_frame.word_wrap = True
            if ph.text_frame.paragraphs:
                ph.text_frame.paragraphs[0].font.size = Pt(title_font_size)
        elif ph.placeholder_format.idx == 15:
            ph15 = ph
            ph.text = clean_purpose
            ph.left = Inches(0.30)
            ph.top = Inches(subtitle_top)
            ph.width = Inches(6.85)
            ph.height = Inches(purpose_h)
            ph.text_frame.word_wrap = True
            if ph.text_frame.paragraphs:
                ph.text_frame.paragraphs[0].font.size = Pt(26)

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
        (str(len(result.observations)), "reported values"),
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
    from .executive_brief import display_brief
    brief_title, selected_brief = display_brief(result)
    if selected_brief:
        from .presentation_summary import render_complete_summary
        notes = result.executive_brief.model_dump_json(indent=2) if result.executive_brief else ''
        render_complete_summary(presentation, brief_title, selected_brief,
                                notes=notes, single_column=True)
        return
    from .presentation_brief import overview_items, render_brief
    items, notes = overview_items(result.profile)
    title = result.profile.overview_title.strip() or "Document overview"
    source_visual = getattr(presentation, "_ada_source_visual", None)
    if source_visual:
        from .presentation_source_visual import render_profile_with_source
        render_profile_with_source(presentation, title, items, source_visual, notes=notes)
    else:
        render_brief(presentation, title, items, notes=notes, excerpt=not bool(result.profile.overview_points))


def _add_text_pages(presentation: Any, title: str, body: str, pages, *, subtitle: str = "") -> None:
    """Retain complete narrative at readable size, continuing when necessary."""
    from .slide_compositor import _base
    from .text_capacity import wrap_copy
    remaining = body
    part = 0
    while remaining:
        slide, top = _base(presentation, title + (" (continued)" if part else ""), subtitle if not part else "")
        width = presentation.slide_width.inches - 1.5
        height = presentation.slide_height.inches - 1.15 - top
        lines = wrap_copy(remaining, width, 18)
        count = max(1, int(height * 72 / 24) - 1)
        shown = "".join(lines[:count])
        tail = "".join(lines[count:])
        if tail:
            # Prefer whole sentences without dropping any overflow text.
            boundaries = [m.end() for m in re.finditer(r"\n\s*\n|[.!?。！？](?:\s+|$)", shown)]
            boundary = next((end for end in reversed(boundaries) if end >= len(shown) * .5), None)
            if boundary:
                tail = shown[boundary:] + tail
                shown = shown[:boundary]
        body_shape = _text(slide, shown, .75, top, width, height, size=18, color=FOURIER_DARK)
        body_shape.name = "narrative:body"
        _text(slide, _source_footer(pages), .55, presentation.slide_height.inches - .82,
              presentation.slide_width.inches - 1.1, .2, size=9, color=FOURIER_MUTED)
        remaining = tail
        part += 1


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
    pages = plan.source_pages

    if movement:
        _text(slide, movement[0], 0.70, content_top + 0.65, 3.05, 0.58, size=21, color=FOURIER_PURPLE, bold=True)
        _text(slide, _summary_text(movement[1], 100), 0.70, content_top + 1.65, 3.05, 0.85, size=12.5, color=FOURIER_DARK)
    else:
        _text(slide, f"{len(values)}", 0.70, content_top + 0.65, 3.05, 0.58, size=21, color=FOURIER_TECH_BLUE, bold=True)
        _text(slide, "comparable reported observations", 0.70, content_top + 1.65, 3.05, 0.85, size=12.5, color=FOURIER_DARK)

    _text(slide, "REPORTED UNIT", 0.70, content_top + 2.95, 3.05, 0.24, size=9.5, color=FOURIER_MUTED, bold=True)
    _text(slide, unit, 0.70, content_top + 3.20, 3.05, 0.45, size=12, color=FOURIER_DARK, bold=True)
    _text(slide, _source_footer(pages), 0.70, content_top + content_h - 0.45, 3.05, 0.35, size=9.5, color=FOURIER_MUTED)

    # Right card: Chart (no background gridlines)
    _panel(slide, 4.20, content_top, 7.95, content_h, fill=WHITE)
    chart_bounds = (4.40, content_top + 0.15, 7.55, content_h - 0.30)
    _add_native_chart(slide, plan, values, chart_bounds)


def _add_chart_plus_kpis_slide(
    presentation: Any,
    plan: ChartPlan,
    index: DocumentIndex,
    *,
    title: str | None = None,
    subtitle: str | None = None,
    supporting_observations: list[Observation] | None = None,
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

    # Left: Large clear Chart (65% width = 7.50 in)
    _panel(slide, 0.45, content_top, 7.50, content_h, fill=WHITE)
    chart_bounds = (0.65, content_top + 0.20, 7.10, content_h - 0.40)
    scale, scale_label = _add_native_chart(slide, plan, values, chart_bounds, compact=False)

    # Right: KPI Cards stack (35% width = 3.95 in)
    right_left = 8.20
    right_width = 3.95
    if supporting_observations and _extract_topic_tokens(display_title):
        temp_slide = PresentationSlide(
            id=f"kpi_{plan.id}",
            slide_type="analysis",
            title=display_title,
            message=display_subtitle or "",
            layout="chart_plus_kpis",
            chart_ids=[plan.id],
        )
        matched_support = [
            item for item in supporting_observations
            if not _is_positive_topic_mismatch(item, temp_slide, is_supporting_kpi=True)
        ]
        # When the requested KPI evidence does not belong to the slide topic,
        # fall back to chart evidence rather than displaying unrelated metrics.
        kpi_items = (matched_support or values[-4:])[:4]
    elif supporting_observations:
        kpi_items = supporting_observations[:4]
    else:
        kpi_items = values[-4:]
    kpi_count = min(len(kpi_items), 4)
    card_h = min(1.05, (content_h - (kpi_count - 1) * 0.12) / max(kpi_count, 1))

    for k_idx, item in enumerate(kpi_items[:kpi_count]):
        card_y = content_top + k_idx * (card_h + 0.12)
        _panel(slide, right_left, card_y, right_width, card_h, fill=FOURIER_BG_CARD)
        semantic = classify_metric(display_metric_name(item), value=item.value, raw_unit=item.raw_unit, unit=item.unit)
        short_title = semantic.short_display_name or semantic.clean_name
        is_bs = any(term in short_title.casefold() for term in ("liabilit", "cash", "balance", "receiv", "payab", "inventor", "asset", "equity", "deficit"))
        period_str = format_observation_period(item) or format_period_label(item.period, is_balance_sheet=is_bs) or item.period or ""
        val_str = format_metric_display_value(item.raw_value, item.value, semantic, raw_unit=_display_source_unit(item), currency=item.currency, compact=True)

        _text(slide, _summary_text(short_title, 32), right_left + 0.18, card_y + 0.10, right_width - 0.36, 0.24, size=11, color=FOURIER_MUTED, bold=True)
        _text(slide, val_str, right_left + 0.18, card_y + 0.38, right_width * 0.58, 0.38, size=16, color=FOURIER_DARK, bold=True)
        if period_str:
            _text(slide, period_str, right_left + right_width * 0.58, card_y + 0.42, right_width * 0.38, 0.28, size=10.5, color=FOURIER_TECH_BLUE, bold=True, align="right")
        pages = ", ".join(map(str, sorted({s.page for s in item.evidence})))
        if pages:
            _text(slide, f"p. {pages}", right_left + 0.18, card_y + card_h - 0.22, right_width - 0.36, 0.18, size=8.5, color=FOURIER_MUTED, align="right")


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

    seen_panel_titles: set[str] = set()
    for position, (plan, bounds) in enumerate(zip(plans[:count], panel_bounds)):
        observations = [index.get(identifier) for identifier in plan.observation_ids]
        values = [item for item in observations if item and item.value is not None]
        left, top, panel_width, panel_height = bounds
        _panel(slide, left, top, panel_width, panel_height, fill=FOURIER_BG_CARD)

        metric_name = display_metric_name(values[0]) if values else ""
        chart_title = _presentation_chart_title(plan.title, values)
        if title and chart_title.casefold() == title.casefold():
            chart_title = metric_name or chart_title
        if chart_title.casefold() in seen_panel_titles:
            chart_title = metric_name or f"{chart_title} ({position + 1})"
        seen_panel_titles.add(chart_title.casefold())

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
        # Fixed vertical slots inside each KPI/chart block:
        # Slot 1: Metric label (top at top + 0.15, height 0.38)
        # Chart canvas: top + 0.55 to top + panel_height - 1.25
        # Slot 2: Movement headline text
        # Slot 3: Period comparison detail
        # Slot 4 & 5: Reported unit and Source/page label
        footer_height = 1.25
        chart_bounds = (left + 0.15, top + 0.55, panel_width - 0.30, panel_height - 0.55 - footer_height)
        scale, scale_label = _add_native_chart(slide, plan, values, chart_bounds, compact=True)
        movement = _change_summary(values, scale)
        unit = _unit_label(values, scale_label)
        pages = ", ".join(map(str, plan.source_pages)) or "not available"

        slot_w = panel_width - 0.36
        slot_left = left + 0.18

        # Fixed Slot 2: Movement text (y = top + panel_height - 1.20, h = 0.28)
        slot2_y = top + panel_height - 1.20
        if movement:
            _text(
                slide,
                _summary_text(movement[0], 48 if not compact_panel else 36),
                slot_left,
                slot2_y,
                slot_w,
                0.28,
                size=11.5 if not compact_panel else 10.5,
                color=CHART_PALETTE[position % len(CHART_PALETTE)],
                bold=True,
            )
        else:
            _text(
                slide,
                f"{len(values)} comparable reported values",
                slot_left,
                slot2_y,
                slot_w,
                0.28,
                size=10.0,
                color=FOURIER_MUTED,
                bold=True,
            )

        # Fixed Slot 3: Period comparison detail (y = slot2_y + 0.32, h = 0.26)
        slot3_y = slot2_y + 0.32
        detail_text = movement[1] if movement else ""
        if detail_text:
            _text(
                slide,
                _summary_text(detail_text, 60 if not compact_panel else 48),
                slot_left,
                slot3_y,
                slot_w,
                0.26,
                size=8.5,
                color=FOURIER_DARK,
            )

        # Fixed Slot 4 & 5: Reported Unit & Source/page label (y = slot3_y + 0.30, h = 0.22)
        slot4_y = slot3_y + 0.30
        unit_w = slot_w * 0.58
        pages_w = slot_w * 0.40
        _text(slide, _summary_text(unit, 30), slot_left, slot4_y, unit_w, 0.22, size=8.0, color=FOURIER_MUTED)
        _text(slide, f"p. {_summary_text(pages, 16)}", slot_left + unit_w + 0.04, slot4_y, pages_w, 0.22, size=8.0, color=FOURIER_MUTED, align="right")


def _chart_number_format(values: list[float]) -> str:
    """Determine dynamic number format preserving signed notation and necessary precision."""
    valid = [float(v) for v in values if v is not None]
    if not valid:
        return "0.0;-0.0;0.0"
    # If any value requires 2 decimal places (e.g. -1.57, -1.13, -0.83)
    if any(round(v, 1) != round(v, 2) for v in valid):
        return "0.00;-0.00;0.00"
    if any(round(v, 0) != round(v, 1) for v in valid):
        return "0.0;-0.0;0.0"
    return "#,##0;-#,##0;0"


def _chart_category_labels(categories: list[str], width: float) -> list[str]:
    """Wrap crowded dates without removing the day, year or audit marker."""
    if width >= 7 or len(categories) < 4:
        return categories
    return [re.sub(r"^(\d{1,2}\s+[A-Za-z]{3})\s+((?:19|20)\d{2}\*?)$", r"\1\n\2", label)
            for label in categories]


def _add_native_chart(
    slide: Any,
    plan: ChartPlan,
    values: list[Observation],
    bounds: tuple[float, float, float, float],
    *,
    compact: bool = False,
    totals: list[Observation] | None = None,
) -> tuple[float, str]:
    from .composition_data import uses_composition_data
    if uses_composition_data(plan):
        from .composition_renderer import add_composition_chart
        return add_composition_chart(slide, plan, values, bounds, totals=totals, compact=compact)
    from pptx.chart.data import CategoryChartData, XyChartData
    from pptx.enum.chart import (
        XL_CHART_TYPE,
        XL_DATA_LABEL_POSITION,
        XL_LEGEND_POSITION,
        XL_TICK_LABEL_POSITION,
    )
    from pptx.util import Inches, Pt

    max_abs = max(abs(float(item.value or 0)) for item in values)
    scale, scale_label = _display_scale(values, max_abs)
    chart_left, chart_top, chart_width, chart_height = (Inches(value) for value in bounds)

    # Detect balance sheet metric for interim date formatting
    metric_name = plan.title or (values[0].metric_original if values else "")
    is_bs = any(term in metric_name.casefold() for term in ("liabilit", "cash", "balance", "receiv", "payab", "inventor"))
    has_negative = False
    has_positive = False
    scaled_vals: list[float] = []

    is_valid_scatter = False
    if plan.chart_type == "scatter" and plan.x_metric and plan.y_metric:
        num_pat = re.compile(r"^\s*[-+]?(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d+)?\s*$")
        if (
            not num_pat.match(plan.x_metric)
            and not num_pat.match(plan.y_metric)
            and re.search(r"[A-Za-z\u4e00-\u9fa5]", plan.x_metric)
            and re.search(r"[A-Za-z\u4e00-\u9fa5]", plan.y_metric)
        ):
            pairs = paired_observations(values, plan.x_metric, plan.y_metric)
            if len(pairs) >= 5:
                has_arbitrary_cats = any(
                    any(isinstance(v, str) and num_pat.match(v) and "." in v for v in item.dimensions.values())
                    for pair in pairs
                    for item in pair
                )
                if not has_arbitrary_cats:
                    is_valid_scatter = True

    if is_valid_scatter:
        data = XyChartData()
        series_title = f"{shorten_metric_title(plan.y_metric)} vs {shorten_metric_title(plan.x_metric)}"
        series = data.add_series(series_title)
        for left, right in paired_observations(values, plan.x_metric, plan.y_metric):
            series.add_data_point(float(left.value or 0) / scale, float(right.value or 0) / scale)
        chart = slide.shapes.add_chart(XL_CHART_TYPE.XY_SCATTER, chart_left, chart_top, chart_width, chart_height, data).chart
    else:
        rows = _series_rows(plan, values, is_balance_sheet=is_bs)
        has_negative = any(row[2] is not None and row[2] < 0 for row in rows)
        has_positive = any(row[2] is not None and row[2] > 0 for row in rows)
        numeric_vals = [row[2] for row in rows if row[2] is not None]
        scaled_vals = [v / scale for v in numeric_vals] if numeric_vals else []
        categories = list(dict.fromkeys(row[0] for row in rows))
        series_names = list(dict.fromkeys(row[1] for row in rows))
        data = CategoryChartData()
        from .presentation_axes import explicit_date_categories
        date_categories = (explicit_date_categories(values, categories)
                           if plan.chart_type in {"line", "area"} else None)
        data.categories = date_categories or _chart_category_labels(categories, bounds[2])
        if date_categories:
            data.categories.number_format = "dd mmm yyyy"
        for name in series_names:
            lookup = {label: value for label, series_name, value in rows if series_name == name}
            data.add_series(name, [lookup.get(label) / scale if lookup.get(label) is not None else None for label in categories])
        effective_chart_type = plan.chart_type
        if effective_chart_type == "area" and not has_complete_period_cadence(categories):
            effective_chart_type = "bar"
        chart_type = {
            "line": XL_CHART_TYPE.LINE_MARKERS,
            "area": XL_CHART_TYPE.AREA,
            "pie": XL_CHART_TYPE.PIE,
            "horizontal_bar": XL_CHART_TYPE.BAR_CLUSTERED,
        }.get(effective_chart_type if effective_chart_type != "scatter" else "line", XL_CHART_TYPE.COLUMN_CLUSTERED)
        chart = slide.shapes.add_chart(chart_type, chart_left, chart_top, chart_width, chart_height, data).chart

    chart.has_title = False
    _normalize_axis_ids(chart)
    chart.has_legend = plan.chart_type == "pie" or len(getattr(chart, "series", [])) > 1
    if chart.has_legend:
        # Position legend at TOP so it never collides with panel footers or explanatory text
        chart.legend.position = XL_LEGEND_POSITION.TOP
        chart.legend.font.name = FONT
        chart.legend.font.size = Pt(8.0 if (compact or bounds[2] < 5.5) else 9.5)
        chart.legend.font.color.rgb = _rgb(FOURIER_DARK)
    chart.chart_style = None
    chart.font.name = FONT
    chart.font.size = Pt(10 if compact else 11)
    chart.font.color.rgb = _rgb(FOURIER_DARK)
    from .presentation_style import chart_color, deck_color_map
    keys = categories if plan.chart_type == "pie" else [series.name for series in chart.series]
    colors = deck_color_map(keys, groups=[keys], preferred=getattr(slide, "_ada_colors", {}))
    for series_index, series in enumerate(chart.series):
        color = FOURIER_PURPLE if plan.chart_type == "pie" else chart_color(series.name, colors)
        try:
            series.format.fill.solid()
            series.format.fill.fore_color.rgb = _rgb(color)
            series.format.line.color.rgb = _rgb(color)
            if chart.chart_type in {XL_CHART_TYPE.LINE_MARKERS, XL_CHART_TYPE.XY_SCATTER}:
                series.marker.format.fill.solid()
                series.marker.format.fill.fore_color.rgb = _rgb(color)
                series.marker.format.line.color.rgb = _rgb(color)
            if plan.chart_type == "pie":
                for point, category in zip(series.points, categories):
                    point.format.fill.solid()
                    point.format.fill.fore_color.rgb = _rgb(chart_color(category, colors))
                    point.format.line.fill.background()
            # Office otherwise inverts negative columns to a white fill,
            # making losses and expense ratios nearly invisible on white slides.
            if chart.chart_type in {XL_CHART_TYPE.COLUMN_CLUSTERED, XL_CHART_TYPE.BAR_CLUSTERED}:
                series.invert_if_negative = False
        except (AttributeError, ValueError):
            pass

    num_fmt = _chart_number_format(scaled_vals)
    label_fmt = num_fmt
    if (scale > 1 and values and all(item.unit == "count" or item.unit_family == "count" for item in values)
            and all(float(item.value).is_integer() for item in values if item.value is not None)):
        # Scaling whole counts must retain every unit in the data labels.
        # The axis may remain compact; its unit label declares the same scale.
        digits = len(str(int(scale))) - 1
        label_fmt = "#,##0." + "0" * digits + ";-#,##0." + "0" * digits + ";0"

    try:
        chart.plots[0].has_data_labels = plan.show_data_labels
        labels = chart.plots[0].data_labels
        if plan.chart_type == "pie":
            labels.position = XL_DATA_LABEL_POSITION.OUTSIDE_END
        elif chart.chart_type in {XL_CHART_TYPE.LINE_MARKERS, XL_CHART_TYPE.AREA}:
            labels.position = XL_DATA_LABEL_POSITION.ABOVE
        else:
            labels.position = XL_DATA_LABEL_POSITION.OUTSIDE_END
        labels.font.name = FONT
        labels.font.color.rgb = _rgb(FOURIER_DARK)
        if has_negative and has_positive:
            # Zero-crossing bar labels: use compact size to prevent crowding x-axis
            labels.font.size = Pt(9 if compact else 10.5)
            # If vertical space is too cramped (< 2.2 in), hide labels to prevent collision with x-axis
            if bounds[3] < 2.2:
                chart.plots[0].has_data_labels = False
        elif chart.chart_type == XL_CHART_TYPE.COLUMN_CLUSTERED and len(chart.series) >= 3:
            # Neighboring categories with similar heights need labels that fit
            # individual columns, not the single-series headline font.
            labels.font.size = Pt(9.5 if bounds[2] < 7 else 11)
        else:
            labels.font.size = Pt(12 if compact or bounds[3] < 2.2 else 14)
        labels.font.bold = True
        # Signed dynamic format preserves minus sign and exact precision
        labels.number_format = label_fmt
        labels.number_format_is_linked = False
        if (compact and chart.chart_type == XL_CHART_TYPE.LINE_MARKERS
                and len(categories) >= 5 and len(chart.series) == 1):
            # Keep endpoints and the largest interior turning point readable.
            # Source values remain in the editable workbook and slide notes.
            values_by_point = list(chart.series[0].values)
            if all(value is not None for value in values_by_point):
                visible = {0, len(values_by_point) - 1}
                turns = [i for i in range(1, len(values_by_point)-1)
                         if (values_by_point[i]-values_by_point[i-1])
                            * (values_by_point[i+1]-values_by_point[i]) < 0]
                if turns:
                    visible.add(max(turns, key=lambda i: abs(values_by_point[i] - (
                        values_by_point[0] + (values_by_point[-1]-values_by_point[0])
                        * i/(len(values_by_point)-1)))))
                from pptx.oxml.xmlchemy import OxmlElement
                for point_index, point in enumerate(chart.series[0].points):
                    if point_index in visible:
                        continue
                    label = point.data_label._get_or_add_dLbl()
                    flag = label.xpath('c:showVal')
                    if flag:
                        flag[0].set('val', '0')
                    else:
                        hidden = OxmlElement('c:showVal')
                        hidden.set('val', '0')
                        label.append(hidden)
    except (AttributeError, ValueError):
        pass
    try:
        # Style axis fonts and DISABLE ALL BACKGROUND GRIDLINES
        if hasattr(chart, "category_axis") and chart.category_axis is not None:
            chart.category_axis.tick_labels.font.name = FONT
            chart.category_axis.tick_labels.font.color.rgb = _rgb(FOURIER_DARK)
            chart.category_axis.format.line.color.rgb = _rgb(FOURIER_BORDER)
            chart.category_axis.tick_labels.font.size = Pt(10 if compact else 11)
            chart.category_axis.has_major_gridlines = False
            chart.category_axis.has_minor_gridlines = False
            if has_negative:
                chart.category_axis.tick_label_position = XL_TICK_LABEL_POSITION.LOW

        if hasattr(chart, "value_axis") and chart.value_axis is not None:
            chart.value_axis.tick_labels.font.name = FONT
            chart.value_axis.tick_labels.font.color.rgb = _rgb(FOURIER_DARK)
            chart.value_axis.format.line.color.rgb = _rgb(FOURIER_BORDER)
            chart.value_axis.tick_labels.font.size = Pt(10 if compact else 11)
            # Signed format preserves minus signs on axis tick labels
            chart.value_axis.tick_labels.number_format = num_fmt
            chart.value_axis.tick_labels.number_format_is_linked = False
            # Clean institutional styling: NO BACKGROUND HORIZONTAL GRIDLINES
            chart.value_axis.has_major_gridlines = False
            chart.value_axis.has_minor_gridlines = False
            chart.value_axis.has_title = False

            from .presentation_axes import style_value_range
            style_value_range(chart.value_axis, scaled_vals, height=bounds[3])
            if has_negative:
                chart.category_axis.tick_label_position = XL_TICK_LABEL_POSITION.LOW
        if not is_valid_scatter and date_categories:
            from .presentation_axes import style_date_axis, label_source_dates
            style_date_axis(chart, date_categories, bounds[2])
            label_source_dates(chart, date_categories, width=bounds[2])
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
    from .presentation_brief import BriefItem, render_brief

    findings = []
    seen_titles = set()
    seen_inputs = set()
    by_task = {r.task_id: r for r in result.analysis_results}
    model_findings = []
    for insight in sorted(result.insights, key=lambda item: (item.importance, item.confidence), reverse=True):
        ids = {oid for rid in insight.result_ids if rid in by_task for oid in by_task[rid].input_observation_ids}
        if ids and frozenset(ids) in seen_inputs:
            continue
        if _is_calc_artifact(insight.narrative) or _is_calc_artifact(insight.title):
            # Reuse the existing evidence/units/period gates. No title matching
            # or invented units: only the insight's actual input IDs qualify.
            candidates = _chart_findings([ChartPlan(id="brief-" + insight.id,
                title=insight.title, question="", chart_type="line", observation_ids=sorted(ids))], index) if ids else []
            if not candidates:
                continue
            finding = candidates[0]
        else:
            if not insight.evidence:
                continue
            finding = {"title": insight.title, "narrative": insight.narrative,
                       "pages": sorted({source.page for source in insight.evidence})}
        model_findings.append(finding)
        if ids:
            seen_inputs.add(frozenset(ids))
    extra_charts = [c for c in charts if frozenset(c.observation_ids) not in seen_inputs]
    for finding in [*model_findings, *_chart_findings(extra_charts, index)]:
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

    notes = "\n\n".join(f"{i.title}\n{i.narrative}\n{_source_footer([e.page for e in i.evidence])}"
                        for i in result.insights)
    render_brief(presentation, "Key findings", [BriefItem(str(f["title"]), str(f["narrative"]),
                 list(f.get("pages", []))) for f in findings], notes=notes)


def _add_quality_slide(presentation: Any, result: PipelineResult, *, title: str = "Limits that affect interpretation") -> None:
    slide = _base_slide(presentation, title, "Data quality notes and validation warnings")
    content_top, content_h = _content_zone(slide)
    from .presentation_identity import presentation_quality_notes
    raw_messages = presentation_quality_notes(result)[:5]

    from adaptive_document_agent.services.company_extractor import is_company_identity_resolved

    is_company_resolved = is_company_identity_resolved(result.presentation_plan.company) if result.presentation_plan else False
    unnamed_phrases = (
        "issuer/company name is not stated",
        "company name is not stated",
        "issuer name is not stated",
        "unnamed issuer",
        "issuer unnamed",
        "issuer unknown",
        "company unnamed",
        "unnamed company",
        "unidentified issuer",
    )
    messages = []
    validation_messages = {w.message for w in result.validation_warnings}
    for msg in raw_messages:
        if msg not in validation_messages and re.search(r"(?i)\b(?:un)?audited\b", msg):
            messages.append("Audit qualifications apply to specific source columns. Interim periods and non-year-end dates do not, by themselves, establish audit status; consult the cited source tables.")
        elif any(phrase in msg.casefold() for phrase in unnamed_phrases) or re.search(r"(?i)(?:company|issuer)(?:\s+legal)?\s+name\s+is\s+not\s+(?:stated|provided|disclosed)", msg):
            if is_company_resolved:
                messages.append(
                    "Company identity is established from introductory/source pages; the selected analysis excerpt may refer to the issuer without repeating its legal name."
                )
            else:
                messages.append(msg)
        else:
            messages.append(msg)

    slide.notes_slide.notes_text_frame.text = "Source scope and data-quality notes:\n" + "\n".join(raw_messages)
    messages = list(dict.fromkeys(messages))

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


THEME_ORDER = [
    "Financial Performance",
    "Liquidity",
    "Working Capital & Operations",
    "Capital Structure & Indebtedness",
    "Cash Flow",
    "Non-IFRS / Adjusted Measures",
    "Financial Overview",
    "Reported Measures",
]


def _classify_financial_theme(metric_name: str, parent_section: str = "") -> str:
    combined = f"{parent_section} {metric_name}".casefold()
    if any(k in combined for k in ("non-ifrs", "non-gaap", "adjusted net", "adjusted ebitda", "adjusted profit", "adjusted loss", "adjusted operating")):
        return "Non-IFRS / Adjusted Measures"
    if any(k in combined for k in ("cash flow", "operating activit", "investing activit", "financing activit", "free cash flow", "cash generated from")):
        return "Cash Flow"
    if any(k in combined for k in ("borrowing", "bank loan", "gearing", "leverage", "total debt", "net debt", "share capital", "total equity", "indebtedness")):
        return "Capital Structure & Indebtedness"
    if any(k in combined for k in ("inventor", "receiv", "payab", "turnover day", "turnover period", "days sales", "contract asset")):
        return "Working Capital & Operations"
    # Do not match "current assets" inside a non-current balance. Preserve the
    # stronger cash-flow, debt and source-context classifications above.
    noncurrent = re.search(r"\bnon[ -]?current\s+(?:assets?|liabilit(?:y|ies))\b", metric_name, re.I)
    if not noncurrent and any(k in combined for k in ("cash and cash", "cash equivalent", "bank balance", "liquid", "current asset", "current liabilit", "quick ratio", "current ratio", "working capital")):
        return "Liquidity"
    if any(k in combined for k in ("revenue", "turnover", "gross profit", "operating profit", "operating loss", "profit for the", "loss for the", "net profit", "net loss", "ebit", "margin", "cost of sales", "selling expense", "administrative expense", "r&d", "research and dev")):
        return "Financial Performance"
    return "Financial Overview"


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
    from .language_qa import clean_display_copy

    observations = _appendix_observations(result, charts)
    # Realign title if mislabeled with offering/proceeds without offering data
    is_offering_title = any(w in title.casefold() for w in ("offering", "proceeds"))
    has_offering_data = any(
        "offering" in display_metric_name(o).casefold() or "proceeds" in display_metric_name(o).casefold()
        for o in (observations or result.observations)
    )
    if is_offering_title and not has_offering_data:
        title = "Key data appendix"

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

    # Extract clean periods and metrics grouped by theme
    # theme -> metric_label -> {"periods": {period_str: val_str}, "pages": set()}
    metrics_by_theme: dict[str, dict[str, dict[str, Any]]] = {}
    from adaptive_document_agent.document_model.series import is_generic_metric_label, metric_identity_key, source_context_key
    name_contexts: dict[str, set[tuple[str, str]]] = {}
    for item in observations:
        name_contexts.setdefault(display_metric_name(item), set()).add(source_context_key(item))
    all_periods_set: set[str] = set()
    from .presentation_share_claims import source_total_denominators
    from .presentation_labels import source_share_heading
    denominators = source_total_denominators(result)
    thematic_labels = {}
    if result.presentation_plan and result.presentation_plan.themes:
        from adaptive_document_agent.validation.narrative_plan_validator import expanded_observation_ids
        chart_map = {c.id: c for c in result.charts}
        for theme_plan in result.presentation_plan.themes:
            for oid in expanded_observation_ids(theme_plan, chart_map):
                thematic_labels.setdefault(oid, theme_plan.title)

    for item in observations:
        semantic = classify_metric(
            display_metric_name(item),
            value=item.value,
            raw_unit=item.raw_unit,
            unit=item.unit,
        )
        metric_name = clean_display_copy(sanitize_metric_label(semantic.clean_name))
        metric_name = source_share_heading(metric_name, [item], denominators)
        categories = item.category_dimensions or {
            k: v for k, v in item.dimensions.items()
            if k not in {"table_context", "section", "period_basis", "column_role", "reporting_basis", "basis", "restatement", "restated", "ifrs_status"}
        }
        if categories:
            metric_name += " — " + ", ".join(str(v) for _, v in sorted(categories.items()))
        if len(name_contexts.get(display_metric_name(item), ())) > 1:
            contexts = sorted(name_contexts[display_metric_name(item)])
            metric_name += f" [source {contexts.index(source_context_key(item)) + 1}]"
        theme = _classify_financial_theme(
            metric_name,
            item.parent_section or item.source_section or item.dimensions.get("section") or "",
        )
        if item.id in thematic_labels:
            theme = thematic_labels[item.id]
        elif theme == "Financial Overview" and not item.currency and not is_financial_statement_metric(metric_name):
            theme = "Reported Measures"
        unit_str = _appendix_display_unit(item, semantic)
        display_value = _appendix_display_value(item, semantic)
        is_item_bs = any(term in metric_name.casefold() for term in ("liabilit", "cash", "balance", "receiv", "payab", "inventor", "asset", "equity", "deficit"))
        period_key = format_observation_period(item) or format_period_label(item.period, is_balance_sheet=is_item_bs) or item.period or "Reported"
        all_periods_set.add(period_key)

        theme_dict = metrics_by_theme.setdefault(theme, {})
        identity = metric_identity_key(item)
        if not item.period:
            # Unknown column semantics are not evidence of a shared period.
            # Preserve each cell and its original column label, never overwrite
            # or invent a date merely to make an appendix exportable.
            identity = (*identity, "unresolved_period", item.id)
            columns = list(dict.fromkeys(e.column_label for e in item.evidence if e.column_label))
            location = ", ".join(columns) or item.id
            metric_name += f" [{location}; period unspecified]"
        metric_entry = theme_dict.setdefault(identity, {"label": metric_name, "unit": unit_str,
            "periods": {}, "values": {}, "raw_signatures": {}, "records": [], "pages": set()})
        metric_entry["records"].append(item)
        metric_entry["raw_signatures"].setdefault(period_key, set()).add((
            item.raw_value, item.raw_unit, item.unit, item.unit_scale, item.currency,
            item.period, item.period_basis, item.period_type, item.as_of_date, item.audited_status,
        ))

        if period_key in metric_entry["values"] and item.value is not None and metric_entry["values"][period_key] is not None:
            from math import isclose
            if not isclose(float(item.value), float(metric_entry["values"][period_key]), rel_tol=1e-9, abs_tol=1e-9):
                raise ValueError(f"Conflicting appendix values for {metric_name} in {period_key}; cannot overwrite evidence.")
        if period_key not in metric_entry["periods"] or display_value != "—":
            metric_entry["periods"][period_key] = display_value
            metric_entry["values"][period_key] = item.value
        for ev in item.evidence:
            if getattr(ev, "page", None):
                metric_entry["pages"].add(ev.page)

    # Two cited tables may contain the same complete series. Keep every raw
    # observation and both page citations, but show that exact series once in
    # the audience appendix. Different values or incomplete period sets stay
    # separate so a disagreement remains visible.
    for theme_entries in metrics_by_theme.values():
        identical: dict[tuple[object, ...], tuple[object, ...]] = {}
        for identity, entry in list(theme_entries.items()):
            if len(identity) < 7 or len(entry["values"]) < 2:
                continue
            if is_generic_metric_label(str(identity[0])):
                continue
            comparison = (identity[0], identity[2:], entry["unit"],
                          tuple(sorted(entry["values"].items())),
                          frozenset((period, frozenset(values))
                                    for period, values in entry["raw_signatures"].items()))
            retained = identical.get(comparison)
            if retained is None:
                identical[comparison] = identity
                continue
            theme_entries[retained]["pages"].update(entry["pages"])
            theme_entries[retained]["records"].extend(entry["records"])
            del theme_entries[identity]
        remaining_names = [re.sub(r" \[source \d+\]$", "", entry["label"])
                           for entry in theme_entries.values()]
        for entry in theme_entries.values():
            plain = re.sub(r" \[source \d+\]$", "", entry["label"])
            if remaining_names.count(plain) == 1:
                entry["label"] = plain

    from .appendix_source_deduplication import deduplicate_complete_entries
    metrics_by_theme = deduplicate_complete_entries(metrics_by_theme)
    sorted_periods = sorted(all_periods_set, key=period_sort_key)
    if not sorted_periods:
        sorted_periods = ["Reported"]

    FLOW_THEMES = [
        "Financial Performance",
        "Cash Flow",
        "Non-IFRS / Adjusted Measures",
        "Financial Overview",
        "Reported Measures",
    ]
    BS_THEMES = [
        "Liquidity",
        "Working Capital & Operations",
        "Capital Structure & Indebtedness",
    ]
    if thematic_labels:
        # LLM-selected topics drive the new plan's appendix too. Preserve legacy
        # financial grouping only for cached plans without a theme contract.
        FLOW_THEMES = list(metrics_by_theme)
        BS_THEMES = []

    slide_specs: list[tuple[list[str], list[tuple[str, dict[str, dict[str, Any]]]], bool]] = []
    for theme_set, is_bs in [(FLOW_THEMES, False), (BS_THEMES, True)]:
        active_themes = [t for t in theme_set if t in metrics_by_theme]
        if not active_themes:
            continue
        # Shared duration alone does not justify stretching every row across
        # unrelated years. Keep exact period sets in separate native tables.
        period_tables = {}
        for theme in active_themes:
            for identity, entry in metrics_by_theme[theme].items():
                period_groups = {}
                for period in sorted(entry["periods"], key=period_sort_key):
                    period_groups.setdefault(extract_period_basis(period), []).append(period)
                for periods in period_groups.values():
                    for start in range(0, len(periods), 6):
                        key = tuple(periods[start:start + 6])
                        period_tables.setdefault(key, {}).setdefault(theme, {})[identity] = entry
        from .appendix_layout import paginate_themes
        for p_chunk, themes in period_tables.items():
            from .appendix_source_deduplication import deduplicate_period_entries
            themes = deduplicate_period_entries(themes, p_chunk)
            from .text_capacity import wrap_copy
            metric_w = max(2.80, min(3.80, 11.70 - 1.10 - len(p_chunk) * 1.15))
            widths = [metric_w, 1.10] + [(11.70 - metric_w - 1.10) / len(p_chunk)] * len(p_chunk)
            def row_height(values):
                return max(.42, max(len(wrap_copy(str(v), w - .16, 12))
                                    for v, w in zip(values, widths)) * .20 + .16)
            def metric_height(entry):
                return row_height([entry["label"], entry["unit"],
                                   *[entry["periods"].get(p, "—") for p in p_chunk]])
            header_height = row_height(["Financial Metric", "Unit", *p_chunk])
            slide_specs.extend((list(p_chunk), bundle, is_bs)
                               for bundle in paginate_themes(list(themes.items()), capacity=4.45 - header_height,
                                   row_cost=metric_height,
                                   heading_cost=lambda theme: row_height([f"■ {theme.upper()}", "", *[""] * len(p_chunk)])))

    if not slide_specs:
        sorted_periods = sorted(all_periods_set, key=period_sort_key) or ["Reported"]
        all_entries = [(t, metrics_by_theme[t]) for t in THEME_ORDER if t in metrics_by_theme]
        slide_specs.append((sorted_periods, all_entries, False))

    if max_pages is not None:
        slide_specs = slide_specs[:max_pages]

    appendix_slides = []
    for p_chunk, theme_entries, is_bs in slide_specs:
        generic_section = bool(thematic_labels) or all(t == "Reported Measures" for t, _ in theme_entries)
        slide_subtitle = subtitle or "Reported values with separate period headers and source provenance"
        slide = _base_slide(presentation, title, slide_subtitle)
        appendix_slides.append(slide)
        source_notes = []
        page_observations = []
        for _, entries in theme_entries:
            for entry in entries.values():
                for item in entry["records"]:
                    page_observations.append(item)
                    source_notes.append(
                        f"{entry['label']}; id={item.id}; period={item.period}; raw={item.raw_value}; "
                        f"unit={item.raw_unit or item.unit}; context={source_context_key(item)}; "
                        f"pages={sorted({e.page for e in item.evidence})}"
                    )
        slide.notes_slide.notes_text_frame.text = "Data Index source records\n" + "\n".join(source_notes)
        content_top, content_h = _content_zone(slide)

        # Deduplicate and filter out columns that have no values across all metrics in this spec
        active_p_chunk = []
        for p in p_chunk:
            has_val = any(
                m_data["periods"].get(p) not in (None, "", "—")
                for _, metrics_dict in theme_entries
                for m_data in metrics_dict.values()
            )
            if has_val and p not in active_p_chunk:
                active_p_chunk.append(p)

        if not active_p_chunk:
            active_p_chunk = p_chunk[:1] if p_chunk else ["Reported"]

        formatted_headers = ["Metric" if generic_section else "Financial Metric", "Unit"] + active_p_chunk

        table_rows: list[tuple[str, str, list[str], bool]] = []
        slide_pages: set[int] = set()

        for theme, metrics_dict in theme_entries:
            table_rows.append((theme, "", ["" for _ in active_p_chunk], True))
            for m_name, m_data in metrics_dict.items():
                row_vals = [m_data["periods"].get(p, "—") for p in active_p_chunk]
                table_rows.append((m_data["label"], m_data.get("unit", ""), row_vals, False))
                slide_pages.update(m_data["pages"])

        table_top = content_top
        table_h = min(4.50, content_h - 0.35)
        num_rows = len(table_rows) + 1
        num_cols = len(formatted_headers)
        short_table = num_rows <= 5
        body_pt = 12.0
        header_pt = 12.0
        table_shape = slide.shapes.add_table(num_rows, num_cols, Inches(0.45), Inches(table_top), Inches(11.70), Inches(table_h))
        table_shape.name = "evidence:packable"
        table = table_shape.table

        num_p = len(active_p_chunk)
        metric_w = max(2.80, min(3.80, 11.70 - 1.10 - num_p * 1.15))
        unit_w = 1.30
        period_w = (11.70 - metric_w - unit_w) / max(num_p, 1)
        table.columns[0].width = Inches(metric_w)
        table.columns[1].width = Inches(unit_w)
        for col_idx in range(2, num_cols):
            table.columns[col_idx].width = Inches(period_w)

        for col_idx, h_text in enumerate(formatted_headers):
            cell = table.cell(0, col_idx)
            cell.text = clean_display_copy(h_text)
            _cell_style(cell, fill=FOURIER_PURPLE, color=WHITE, bold=True, size=header_pt)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            if col_idx >= 2:
                cell.text_frame.paragraphs[0].alignment = PP_ALIGN.RIGHT
            else:
                cell.text_frame.paragraphs[0].alignment = PP_ALIGN.LEFT

        for row_idx, (row_label, row_unit, row_vals, is_header) in enumerate(table_rows, start=1):
            if is_header:
                cell0 = table.cell(row_idx, 0)
                cell0.text = clean_display_copy(f"■ {row_label.upper()}")
                _cell_style(cell0, fill=FOURIER_BG_CARD, color=FOURIER_PURPLE, bold=True, size=body_pt)
                cell0.vertical_anchor = MSO_ANCHOR.MIDDLE
                cell0.text_frame.paragraphs[0].alignment = PP_ALIGN.LEFT
                for col_idx in range(1, num_cols):
                    cell = table.cell(row_idx, col_idx)
                    cell.text = ""
                    _cell_style(cell, fill=FOURIER_BG_CARD, color=FOURIER_PURPLE, bold=True, size=body_pt)
            else:
                row_fill = WHITE if row_idx % 2 == 0 else FOURIER_BG_CARD
                cell0 = table.cell(row_idx, 0)
                cell0.text = clean_display_copy(row_label)
                _cell_style(cell0, fill=row_fill, color=FOURIER_DARK, bold=False, size=body_pt)
                cell0.text_frame.word_wrap = True
                cell0.vertical_anchor = MSO_ANCHOR.MIDDLE
                cell0.text_frame.paragraphs[0].alignment = PP_ALIGN.LEFT

                cell1 = table.cell(row_idx, 1)
                cell1.text = clean_display_copy(str(row_unit))
                _cell_style(cell1, fill=row_fill, color=FOURIER_DARK, bold=False, size=body_pt)
                cell1.vertical_anchor = MSO_ANCHOR.MIDDLE
                cell1.text_frame.paragraphs[0].alignment = PP_ALIGN.LEFT

                for col_idx, val in enumerate(row_vals, start=2):
                    cell = table.cell(row_idx, col_idx)
                    cell.text = clean_display_copy(str(val))
                    _cell_style(cell, fill=row_fill, color=FOURIER_DARK, bold=False, size=body_pt)
                    cell.vertical_anchor = MSO_ANCHOR.MIDDLE
                    cell.text_frame.paragraphs[0].alignment = PP_ALIGN.RIGHT

        from .text_capacity import wrap_copy
        from copy import deepcopy
        for table_row_index, row in enumerate(table.rows):
            lines = []
            for cell, col in zip(row.cells, table.columns):
                wrapped = wrap_copy(cell.text, col.width.inches - .16,
                                    header_pt if table_row_index == 0 else body_pt)
                properties = deepcopy(cell.text_frame.paragraphs[0]._p.pPr)
                cell.text = "\n".join(wrapped)
                if properties is not None:
                    for paragraph in cell.text_frame.paragraphs:
                        paragraph._p.insert(0, deepcopy(properties))
                cell.text_frame.word_wrap = True
                lines.append(len(wrapped))
            row.height = Inches(max(.55 if short_table else .38,
                                    max(lines) * (body_pt / 72 * 1.15) + .13))

        has_unaudited = any("*" in h for h in formatted_headers[1:])
        star_note = " | * Unaudited" if has_unaudited else ""
        pages_str = _source_footer(slide_pages)
        footnote = f"{pages_str}{star_note} | Rounded display; — = no retained value. Source variants and exact values: CSV."
        from .presentation_conventions import signed_expense_note
        convention = signed_expense_note(page_observations)
        if convention:
            _text(slide, convention, 0.45, max(5.90, table_shape.top.inches + table_shape.height.inches + .08), 11.70, 0.28, size=10, color=FOURIER_MUTED).name = "evidence:convention"
        _text(slide, footnote, 0.45, 6.22, 11.70, 0.25, size=9.0, color=FOURIER_MUTED).name = "evidence:footer"
    from .evidence_page_packing import pack_evidence_pages
    pack_evidence_pages(presentation, appendix_slides, first_fit=True)


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
    from adaptive_document_agent.services.language_qa import clean_display_copy, polish_slide_title

    clean_title = polish_slide_title(_summary_text(clean_display_copy(title), 118))
    clean_subtitle = _summary_text(clean_display_copy(subtitle), 175) if subtitle else ""
    layout_idx = 5 if len(clean_title) <= 52 else 6
    if layout_idx < len(presentation.slide_layouts):
        slide = presentation.slides.add_slide(presentation.slide_layouts[layout_idx])
    else:
        slide = presentation.slides.add_slide(presentation.slide_layouts[0])

    slide._ada_colors = getattr(presentation, "_ada_colors", {})

    _style_content_header(slide, clean_title, clean_subtitle)
    return slide


def _style_content_header(slide: Any, title: str, subtitle: str) -> None:
    """Reflow the template's Arial 32/18 header without moving its logo."""
    from .text_capacity import wrap_copy
    title_ph = None
    sub_ph = None
    for ph in slide.placeholders:
        if ph.placeholder_format.idx in (14, 15):
            title_ph = ph
        elif ph.placeholder_format.idx == 16:
            sub_ph = ph

    if title_ph is not None:
        title_ph.text = title
        title_ph.text_frame.word_wrap = True
        lines = wrap_copy(title, 8.91, 32)
        if len(lines) > 3:
            raise ValueError("Presentation title exceeds readable capacity; shorten the planned title.")
        update_geometry(title_ph, left=.30, top=.27, width=9.06,
                        height=max(.50, len(lines) * 32 / 72 * 1.22 + .02))
        title_ph.text_frame.margin_left = title_ph.text_frame.margin_right = Inches(.02)
        title_ph.text_frame.margin_top = title_ph.text_frame.margin_bottom = Inches(.01)
        for p in title_ph.text_frame.paragraphs:
            # Header roles are flush left. Explicit paragraph geometry avoids
            # inheriting the template's body-placeholder hanging indentation.
            properties = p._p.get_or_add_pPr()
            properties.set("marL", "0")
            properties.set("indent", "0")
            properties.set("algn", "l")
            p.font.name = FONT
            p.font.size = Pt(32)
            p.font.bold = True
            p.font.color.rgb = _rgb(FOURIER_DARK)

    if sub_ph is not None:
        if subtitle:
            sub_ph.text = subtitle
            sub_ph.text_frame.word_wrap = True
            lines = wrap_copy(subtitle, 8.91, 18)
            if len(lines) > 3:
                raise ValueError("Presentation subtitle exceeds readable capacity; move detail to commentary.")
            sub_top = title_ph.top.inches + title_ph.height.inches + .08 if title_ph is not None else .84
            update_geometry(sub_ph, left=.30, top=sub_top, width=9.07,
                            height=max(.33, len(lines) * 18 / 72 * 1.22 + .02))
            sub_ph.text_frame.margin_left = sub_ph.text_frame.margin_right = Inches(.02)
            sub_ph.text_frame.margin_top = sub_ph.text_frame.margin_bottom = Inches(.01)
            for p in sub_ph.text_frame.paragraphs:
                properties = p._p.get_or_add_pPr()
                properties.set("marL", "0")
                properties.set("indent", "0")
                properties.set("algn", "l")
                p.font.name = FONT
                p.font.size = Pt(18)
                p.font.bold = False
                p.font.color.rgb = _rgb(FOURIER_PURPLE)
        else:
            sub_ph.text = ""


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
    from .language_qa import clean_display_copy

    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    frame = box.text_frame
    frame.clear()
    frame.word_wrap = True
    frame.margin_left = frame.margin_right = Inches(0.02)
    frame.margin_top = frame.margin_bottom = Inches(0.01)
    frame.vertical_anchor = MSO_ANCHOR.TOP
    paragraph = frame.paragraphs[0]
    paragraph.text = clean_display_copy(value)
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
        source_dimensions = {**item.dimensions, **item.category_dimensions}
        label = source_dimensions.get(axis_dimension) if axis_dimension else None
        if not label and item.period:
            label = item.period
        if not label and item.dimensions:
            axis_dimension, label = next(iter(item.dimensions.items()))
        label = label or item.entity or item.metric_original

        # Format label with interim notation if applicable.
        # When the label is the observation's own period, use the full observation metadata
        # for accurate balance-sheet / unaudited detection (avoids FY2025 for Apr 30, 2025).
        if label == item.period and item.period:
            label = format_observation_period(item) or label
        else:
            label = format_period_label(label, is_balance_sheet=is_balance_sheet)

        base_series = str(item.entity or display_metric_name(item))
        ignored_dimensions = {axis_dimension, "table_context", "period_basis", "column_role"}
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
                for key, value in source_dimensions.items()
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
    from .presentation_labels import qualified_metric_name
    series_names = {qualified_metric_name(item) for item in observations}
    if len(series_names) == 1:
        single = next(iter(series_names))
        # A source section or task question may mention an unplotted metric.
        # A single-series fallback names only the evidence actually displayed.
        return single
    names = " / ".join(sorted(series_names, key=str.casefold))
    return names if names and len(names) <= 110 else "Reported measures"


def _change_summary(observations: list[Observation], scale: float) -> tuple[str, str] | None:
    from adaptive_document_agent.document_model.series import metric_identity_key
    if len({metric_identity_key(item) for item in observations}) != 1:
        return None
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

    # Enforce period basis comparability: do not compare FY with 6M directly
    if not are_periods_comparable(ordered[0].period, ordered[-1].period)[0]:
        basis_groups: dict[str, list[Observation]] = {}
        for it in ordered:
            b = extract_period_basis(it.period)
            basis_groups.setdefault(b, []).append(it)
        comparable_candidates = [grp for grp in basis_groups.values() if len(grp) >= 2]
        if not comparable_candidates:
            return None
        # Prefer candidate with the most items, or FY
        ordered = max(comparable_candidates, key=lambda grp: (extract_period_basis(grp[0].period) == "FY", len(grp)))

    first, last = ordered[0], ordered[-1]
    if not are_periods_comparable(first.period, last.period)[0]:
        return None

    start, end = float(first.value or 0), float(last.value or 0)
    ordered_vals = [float(it.value or 0) for it in ordered]

    # Check metric semantic using shared FinancialMovementFormatter
    semantic = classify_metric(first.metric_original, value=start, raw_unit=first.raw_unit, unit=first.unit)
    headline = FinancialMovementFormatter.format_movement_headline(
        first.metric_original,
        start,
        end,
        canonical_name=first.metric_canonical,
        currency=first.currency or "",
        scale=1.0 if first.currency else scale,
        unit=first.unit,
        unit_family=first.unit_family,
        values=ordered_vals,
    )

    p_first = format_canonical_period(first)
    p_last = format_canonical_period(last)
    if semantic.unit_family == "days" or first.unit == "days":
        detail = f"{start:.1f} days in {p_first} to {end:.1f} days in {p_last}"
    elif semantic.is_multiple:
        detail = f"{start:.2f}x in {p_first} to {end:.2f}x in {p_last}"
    elif semantic.is_percentage:
        detail = f"{start:.1f}% in {p_first} to {end:.1f}% in {p_last}"
    else:
        detail = f"{_format_scaled(start, scale)} in {p_first} to {_format_scaled(end, scale)} in {p_last}"

    if len(ordered) >= 3:
        traj = FinancialMovementFormatter.analyze_trajectory(ordered_vals, [format_canonical_period(it) for it in ordered])
        if traj.get("pattern") in ("rose_then_fell_sharply", "rose_then_moderated"):
            peak_idx = ordered_vals.index(max(ordered_vals))
            p_peak = format_canonical_period(ordered[peak_idx])
            v_peak = max(ordered_vals)
            peak_str = f"{v_peak:.1f} days" if (semantic.unit_family == "days" or first.unit == "days") else (f"{v_peak:.1f}%" if semantic.is_percentage else (f"{v_peak:.2f}x" if semantic.is_multiple else _format_scaled(v_peak, scale)))
            end_str = f"{end:.1f} days" if (semantic.unit_family == "days" or first.unit == "days") else (f"{end:.1f}%" if semantic.is_percentage else (f"{end:.2f}x" if semantic.is_multiple else _format_scaled(end, scale)))
            detail = f"Peaked at {peak_str} in {p_peak} before falling to {end_str} in {p_last}"
        elif traj.get("pattern") in ("fell_then_rebounded", "fell_then_partially_recovered"):
            trough_idx = ordered_vals.index(min(ordered_vals))
            p_trough = format_canonical_period(ordered[trough_idx])
            v_trough = min(ordered_vals)
            trough_str = f"{v_trough:.1f} days" if (semantic.unit_family == "days" or first.unit == "days") else (f"{v_trough:.1f}%" if semantic.is_percentage else (f"{v_trough:.2f}x" if semantic.is_multiple else _format_scaled(v_trough, scale)))
            end_str = f"{end:.1f} days" if (semantic.unit_family == "days" or first.unit == "days") else (f"{end:.1f}%" if semantic.is_percentage else (f"{end:.2f}x" if semantic.is_multiple else _format_scaled(end, scale)))
            detail = f"Dipped to {trough_str} in {p_trough} before recovering to {end_str} in {p_last}"
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
            from .text_capacity import wrap_copy
            full_title = _chart_group_title([*group, candidate], index)
            # Plan separate complete headings before the downstream 14-word /
            # 118-character header copy rules could silently drop a metric.
            fits_heading = (len(full_title.split()) <= 14 and len(full_title) <= 118
                            and len(wrap_copy(full_title, 8.91, 32)) <= 3)
            if fits_heading and all(_charts_belong_together(member, candidate, index) for member in group):
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

    # A repeated heading is metadata, not evidence of a common subject. Source
    # context is usable only when every plotted observation is bound to the
    # same retained table and a concrete (non-section-only) context.
    shared_context = bool(_chart_source_contexts(left_values) & _chart_source_contexts(right_values))
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

    from adaptive_document_agent.document_model.series import is_generic_metric_label, metric_label

    left_names = {metric_label(item).strip().casefold() for item in left_values}
    right_names = {metric_label(item).strip().casefold() for item in right_values}
    # "Others" in separate tables is not a single measure, even if semantic
    # resolution assigned it the same canonical label.
    if any(is_generic_metric_label(name) for name in left_names | right_names):
        return False
    same_unit = _chart_unit_signature(left_values) == _chart_unit_signature(right_values)
    same_status = {item.ifrs_status for item in left_values} == {item.ifrs_status for item in right_values}
    if left_names == right_names and same_unit and same_status:
        return True

    # Use every concrete retained metric, never a proposed chart title or just
    # the first canonical label. An extra unpaired series cannot borrow another
    # series' relationship.
    if all(_complementary_metric_names(left_name, right_name)
           for left_name in left_names for right_name in right_names):
        return True

    same_page = bool(_chart_source_pages(left, left_values) & _chart_source_pages(right, right_values))
    shared_terms = _chart_metric_tokens(left_values) & _chart_metric_tokens(right_values)
    return same_page and same_unit and same_status and bool(shared_terms)


def _complementary_metric_names(left_name: str, right_name: str) -> bool:
    """Preserve established metric pairings using evidence labels only."""
    is_margin_cost = (
        ("margin" in left_name or "gross profit" in left_name)
        and ("cost of sales" in right_name or "cost of revenue" in right_name)
    ) or (
        ("margin" in right_name or "gross profit" in right_name)
        and ("cost of sales" in left_name or "cost of revenue" in left_name)
    )
    if is_margin_cost:
        return True

    def is_opex_intensity(name: str) -> bool:
        return any(term in name for term in ("selling", "administrative", "admin", "r&d", "research and development")) and any(
            term in name for term in ("revenue", "%", "share", "ratio"))

    if is_opex_intensity(left_name) and is_opex_intensity(right_name):
        return True

    def is_volume(name: str) -> bool:
        return bool(re.search(r"\b(?:volume|units|shipments?)\b|销量", name))

    def is_price(name: str) -> bool:
        return bool(re.search(r"\b(?:asp|price)\b|单价|平均售价", name))

    return (is_volume(left_name) and is_price(right_name)) or (is_volume(right_name) and is_price(left_name))


def _chart_source_contexts(values: list[Observation]) -> set[tuple[str, str]]:
    """Return concrete context/table bindings shared by every plotted value.

    The legacy source_table field may contain a display heading, so only
    explicit table IDs are identity evidence. Ignore section-only vocabulary
    rather than maintaining document-specific heading exceptions.
    """
    generic_words = {
        "and", "the", "of", "for", "annual", "interim", "financial", "information",
        "section", "results", "operations", "review", "summary", "overview",
        "selected", "reported", "key", "highlights", "measures", "metrics", "data",
        "analysis", "performance", "company", "group", "consolidated", "report",
    }
    common: set[tuple[str, str]] | None = None
    for item in values:
        context = " ".join(item.dimensions.get("table_context", "").casefold().split())
        tokens = set(re.findall(r"[^\W_]+", context, flags=re.UNICODE))
        if not any(token not in generic_words and not token.isdigit() for token in tokens):
            return set()
        table_ids = {identifier for identifier in (item.table_id, *(source.table_id for source in item.evidence)) if identifier}
        bindings = {(context, identifier) for identifier in table_ids}
        common = bindings if common is None else common & bindings
    return common or set()


def _chart_unit_signature(values: list[Observation]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    return (
        tuple(sorted({item.currency or "" for item in values})),
        tuple(sorted({item.unit or "" for item in values})),
    )


def _chart_source_pages(plan: ChartPlan, values: list[Observation]) -> set[int]:
    # A proposed chart's broad page list must not override retained provenance.
    evidence_pages = {source.page for item in values for source in item.evidence}
    return evidence_pages or set(plan.source_pages)


def _chart_metric_tokens(values: list[Observation]) -> set[str]:
    from adaptive_document_agent.document_model.series import metric_label

    ignored = {
        "and", "the", "reported", "values", "value", "analysis", "chart", "total",
        "cost", "costs", "profit", "profits", "expense", "expenses", "revenue",
        "loss", "losses", "income", "net", "gross", "financial", "operating",
        "trajectory", "trend", "performance", "group", "company", "information",
    }
    # Shared vocabulary must occur in every plotted metric, not in a proposed
    # heading or in just one member of a multi-metric chart.
    common: set[str] | None = None
    for item in values:
        tokens = {token for token in re.findall(r"[^\W_]{3,}", metric_label(item).casefold(), flags=re.UNICODE)
                  if token not in ignored and not token.isdigit()}
        common = tokens if common is None else common & tokens
    return common or set()


def _chart_group_title(plans: list[ChartPlan], index: DocumentIndex) -> str:
    """Name all plotted measures completely; callers must fit or paginate them."""
    from .presentation_labels import qualified_metric_name

    titles: list[str] = []
    seen: set[str] = set()
    for plan in plans:
        for identifier in plan.observation_ids:
            item = index.get(identifier)
            if item is None or item.value is None:
                continue
            title = qualified_metric_name(item)
            # Attached numeric footnotes are source markers, not metric data.
            # Keep them on the observation and remove only audience-copy marks.
            title = re.sub(r"(?<=[A-Za-z])\(\d{1,2}\)(?=\s|$)", "", title)
            if title and title.casefold() not in seen:
                titles.append(title)
                seen.add(title.casefold())
    if len(titles) > 1:
        return ", ".join(titles[:-1]) + " and " + titles[-1]
    return titles[0] if titles else "Reported measures"


def _usable_charts(result: PipelineResult) -> list[ChartPlan]:
    from .composition_data import uses_composition_data, composition_data
    from .presentation_evidence import ambiguous_source_table_ids, observation_uses_ambiguous_table
    index = DocumentIndex(result.observations)
    ambiguous_tables = ambiguous_source_table_ids(result)
    output: list[ChartPlan] = []
    for plan in result.charts:
        observations = [index.get(identifier) for identifier in plan.observation_ids]
        if any(item and observation_uses_ambiguous_table(item, ambiguous_tables) for item in observations):
            continue
        observations = [item for item in observations if item and is_meaningful_metric(item)]
        if uses_composition_data(plan):
            composition_data(plan, observations, [index.get(oid) for oid in plan.total_observation_ids if index.get(oid)])
            # An unchanged composition is still a meaningful comparison. Its
            # categories may live in category_dimensions, not legacy dimensions.
            output.append(plan)
            continue
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
    from .composition_data import uses_composition_data
    output: list[dict[str, object]] = []
    seen: set[str] = set()
    for chart in charts:
        if uses_composition_data(chart):
            # A category matrix is not one unsegmented period series.
            continue
        values = [index.get(identifier) for identifier in chart.observation_ids]
        values = [item for item in values if item and item.value is not None and is_meaningful_metric(item)]
        keys = {metric_key(item) for item in values}
        if len(keys) != 1 or not values:
            continue
        from adaptive_document_agent.document_model.series import metric_identity_key
        if len({metric_identity_key(item) for item in values}) != 1:
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
        from adaptive_document_agent.validation.claim_validator import are_observations_compatible
        if any(not are_observations_compatible(first, item)[0] for item in ordered[1:]):
            # The chart can show source periods in parallel, but cannot claim
            # a like-for-like movement across annual and interim durations.
            continue
        scale, scale_label = _display_scale(ordered, max(abs(float(item.value or 0)) for item in ordered))
        label = sanitize_metric_label(display_metric_name(first))
        if not first.currency:
            from .single_metric_analysis import single_metric_analysis
            from .presentation_evidence import evidence_groups
            if len(evidence_groups(values)) != 1:
                continue
            analysis = single_metric_analysis(values)
            unit = "%" if analysis and analysis.is_percentage else "units" if first.unit == "count" else first.unit or ""
            # No currency can be inferred from a missing currency field. This
            # fallback states source levels rather than inventing a narrative.
            narrative = f"{label}: {first.value:,.1f} {unit} in {first.period} and {last.value:,.1f} {unit} in {last.period}."
            if analysis and analysis.turning_periods:
                narrative += f" Peak: {analysis.peak.value:,.1f} {unit} in {analysis.peak.period}; low: {analysis.trough.value:,.1f} {unit} in {analysis.trough.period}."
        else:
            narrative = FinancialMovementFormatter.format_movement_narrative(
                first, last, currency=first.currency, unit=first.unit, unit_family=first.unit_family,
                scale=scale, observations=ordered,
            )
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
    used_ids = [identifier for plan in charts for identifier in [*plan.observation_ids, *plan.total_observation_ids]]
    if result.presentation_plan:
        for slide in result.presentation_plan.slides:
            if slide.slide_type not in {"appendix", "data_quality"}:
                used_ids.extend(slide.observation_ids)
                used_ids.extend(oid for block in slide.visual_blocks for oid in block.observation_ids)
    if result.presentation_plan and result.presentation_plan.themes:
        for theme in result.presentation_plan.themes:
            used_ids.extend(theme.observation_ids)
    selected = [index.get(identifier) for identifier in used_ids]
    pool = [item for item in selected if item is not None and item.value is not None]
    if not result.presentation_plan and (not pool or len(pool) < 8):
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
    if "percent" in units or "percentage" in families or any(is_margin_metric(display_metric_name(item)) for item in observations):
        return "%"
    if "days" in units or "days" in families or any(is_days_metric(display_metric_name(item)) for item in observations):
        return "days"
    is_financial = any(
        is_financial_statement_metric(display_metric_name(item))
        or getattr(item, "is_currency", False)
        or getattr(item, "unit_family", "") == "currency"
        or getattr(item, "currency", None)
        for item in observations
    )
    if ("count" in units or "count" in families or any(getattr(item, "is_volume", False) for item in observations)) and not is_financial:
        return f"{scale_label} units" if scale_label else "units"
    currencies = {item.currency for item in observations if item.currency}
    raw_units = {item.raw_unit for item in observations if item.raw_unit}
    if currencies:
        base = normalize_currency_symbol(next(iter(currencies)))
        from .financial_formatter import split_unit_basis
        bases = {split_unit_basis(item.raw_unit)[1] for item in observations}
        suffix = f"/{next(iter(bases))}" if len(bases) == 1 and "" not in bases else ""
        return (f"{base} {scale_label}" if scale_label else base) + suffix
    if raw_units:
        return normalize_raw_unit(next(iter(raw_units)))
    for item in observations:
        disp_u = getattr(item, "display_unit", None)
        if disp_u and disp_u not in ("unknown", "none", "null", ""):
            return disp_u
    if is_financial:
        return scale_label or "currency unspecified"
    return scale_label or ""


def _display_source_unit(item: Observation) -> str:
    from .financial_formatter import split_unit_basis
    if split_unit_basis(item.raw_unit)[1]:
        return normalize_raw_unit(item.raw_unit, default_currency=item.currency)
    metric_name = display_metric_name(item)
    if is_days_metric(metric_name) or item.unit == "days" or getattr(item, "unit_family", "") == "days":
        return "days"
    if is_margin_metric(metric_name) or item.unit == "percent" or getattr(item, "unit_family", "") == "percentage":
        return "%"
    semantic = classify_metric(metric_name, value=item.value, raw_unit=item.raw_unit, unit=item.unit)
    if semantic.is_multiple:
        return "x"
    if semantic.is_percentage:
        return "%"
    if semantic.unit_family == "days" or is_days_metric(metric_name):
        return "days"
    is_financial = semantic.is_currency or is_financial_statement_metric(metric_name)
    if (semantic.is_volume or semantic.unit_family == "count") and not is_financial:
        return "units"
    if is_financial:
        curr = item.currency or (item.raw_unit if item.raw_unit and item.raw_unit != "units" else None)
        if curr:
            return normalize_raw_unit(curr, default_currency=item.currency)
        return "currency unspecified"
    value = item.raw_unit or _unit_label([item], "")
    if not value or value in ("units", "unknown"):
        disp = getattr(item, "display_unit", None)
        if disp and disp not in ("unknown", "none", "null", ""):
            return disp
        return "units" if (semantic.is_volume or semantic.unit_family == "count") else ""
    return normalize_raw_unit(value, default_currency=item.currency)


def _appendix_display_unit(item: Observation, semantic: Any) -> str:
    """Return a client-facing appendix unit without exposing source-scale tokens.

    Exact source units and values remain on ``Observation`` and in the CSV export.
    The PPT appendix uses one readable monetary scale per row instead.
    """
    from .financial_formatter import split_unit_basis
    if split_unit_basis(item.raw_unit)[1]:
        return normalize_raw_unit(item.raw_unit, default_currency=item.currency)
    if semantic.is_currency:
        from adaptive_document_agent.services.financial_formatter import currency_from_unit

        currency = normalize_currency_symbol(item.currency) or currency_from_unit(item.raw_unit)
        return f"{currency} million" if currency else "million (currency unspecified)"
    return _display_source_unit(item)


def _appendix_display_value(item: Observation, semantic: Any) -> str:
    """Format an appendix cell from normalized numeric evidence when available."""
    from .financial_formatter import split_unit_basis
    if split_unit_basis(item.raw_unit)[1]:
        # The unit keeps its reported scale, so use its corresponding raw cell.
        return str(item.raw_value)
    if not semantic.is_currency or item.value is None:
        from .presentation_conventions import signed_expense_display
        return signed_expense_display(item, str(item.raw_value), with_unit=False)

    if (item.unit_scale or 1.0) > 1.0:
        base_val = float(item.value)
    else:
        source_unit = normalize_raw_unit(item.raw_unit, default_currency=item.currency).casefold()
        scale = 1.0
        if "'000" in source_unit or "thousand" in source_unit:
            scale = 1_000.0
        elif "billion" in source_unit:
            scale = 1_000_000_000.0
        elif "million" in source_unit:
            scale = 1_000_000.0
        base_val = float(item.value) * scale
    value_in_millions = base_val / 1_000_000.0
    if 0 < abs(value_in_millions) < 1:
        # Two decimal places collapse small monetary series (for example,
        # 0.0659 and 0.0566 million both look like 0.06). Keep enough
        # significant digits for the displayed trend without changing units.
        return f"{value_in_millions:,.3g}"
    return f"{value_in_millions:,.2f}".rstrip('0').rstrip('.')


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


def _add_thank_you_slide(presentation: Any) -> None:
    """Append the official FOURIER Thank You slide cloned from template layout."""
    from pptx.util import Inches, Pt

    if len(presentation.slide_layouts) > 14:
        thank_you_layout = presentation.slide_layouts[14]
    else:
        thank_you_layout = presentation.slide_layouts[-1]

    slide = presentation.slides.add_slide(thank_you_layout)
    tb = slide.shapes.add_textbox(Inches(0.87), Inches(2.70), Inches(6.0), Inches(1.0))
    p = tb.text_frame.paragraphs[0]
    p.text = "THANK YOU"
    p.font.name = "Arial"
    p.font.size = Pt(44)
    p.font.bold = True
    p.font.color.rgb = _rgb(FOURIER_DARK)


def _number_slides(presentation: Any) -> None:
    total_count = len(presentation.slides)
    for index, slide in enumerate(presentation.slides, start=1):
        if index == 1:
            continue
        if index == total_count:
            last_text = " ".join(s.text for s in slide.shapes if s.has_text_frame).casefold()
            last_layout = slide.slide_layout.name if hasattr(slide, "slide_layout") else ""
            if "thank you" in last_text or "thank" in last_layout.casefold():
                continue
        _text(slide, str(index), 11.60, 6.53, 0.60, 0.23, size=9, color=FOURIER_MUTED, align="right")


def _page_ranges(result: PipelineResult) -> str:
    ranges = result.profile.analysis_page_ranges
    return ", ".join(f"{start}-{end}" for start, end in ranges) if ranges else f"1-{result.document.page_count}"


def _summary_text(value: str, maximum: int, allow_ellipsis: bool = False) -> str:
    from adaptive_document_agent.services.language_qa import clean_presentation_text
    clean = clean_presentation_text(" ".join(value.replace("—", "-").replace("–", "-").split()))
    if len(clean) <= maximum:
        return clean
    clipped = clean[:maximum].rsplit(" ", 1)[0].rstrip(" ,:;-.")
    if allow_ellipsis:
        return f"{clipped}..." if clipped else f"{clean[:maximum]}..."
    return clipped if clipped else clean[:maximum]
