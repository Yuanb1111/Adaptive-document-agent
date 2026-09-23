"""Deterministic repairer for AI-authored presentation plans.

This module cleans and normalises proposed plans that failed validation:
it removes non-existent IDs, aligns source pages to referenced evidence,
prunes sentences with unsupported numbers, deduplicates company/risk items,
reverts invalid chart type overrides, enforces the chart count limit, fills
standard section titles, drops slides without retained evidence, and preserves
remaining valid AI slides without inventing facts.
"""

from collections import defaultdict
import re

from adaptive_document_agent.models import (
    ChartPlan,
    CompanyFact,
    CompanyProfile,
    PipelineResult,
    PresentationPlan,
    PresentationSlide,
    PresentationVisualBlock,
)
from adaptive_document_agent.services.language_qa import polish_slide_title
from adaptive_document_agent.utils.ids import stable_id
from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator


class PresentationPlanRepairer:
    """Safely repair an invalid presentation plan using deterministic rules only."""

    _numeric_claim = re.compile(r"\d")
    _sentence_split = re.compile(r"(?<=[.!?。！？;；])\s+|\n+")

    def repair(self, plan: PresentationPlan, result: PipelineResult) -> PresentationPlan:
        """Prune unsupported claims, align citations, and validate the resulting plan."""
        # New thematic contracts cannot safely be rebuilt by the legacy repairer's
        # title/topic guesses. Keep valid plans intact, otherwise fail explicitly
        # so the caller can use its labelled evidence-only fallback.
        if plan.themes or any(s.theme_id or s.calculation_ids for s in plan.slides):
            return PresentationPlanValidator().validate(plan, result)
        from adaptive_document_agent.document_model import DocumentIndex, display_metric_name, sanitize_metric_for_title
        from adaptive_document_agent.services.pptx_export import _chart_group_title, _group_chart_plans, _usable_charts

        observations = {item.id: item for item in result.observations}
        insights = {item.id: item for item in result.insights}
        charts = {item.id: item for item in result.charts}
        usable = _usable_charts(result)
        index = DocumentIndex(result.observations)
        valid_pages = set(range(1, result.document.page_count + 1))

        cleaned_company = self._clean_company(plan.company, result, valid_pages)
        repaired_slides: list[PresentationSlide] = []
        pending_under_supported: list[tuple[list[str], str, list[str], list[int], list[str], str]] = []

        for ordinal, slide in enumerate(plan.slides):
            if slide.slide_type not in {
                "cover",
                "company_overview",
                "executive_summary",
                "analysis",
                "risks",
                "data_quality",
                "appendix",
            }:
                continue

            resolved_chart_ids = self._resolve_chart_ids(slide.chart_ids, slide.title, charts, usable)
            chart_ids = resolved_chart_ids[:3]
            observation_ids = self._unique([item for item in slide.observation_ids if item in observations])
            insight_ids = self._unique([item for item in slide.insight_ids if item in insights])

            remaining_chart_capacity = max(0, 3 - len(chart_ids))
            blocks = [
                self._clean_block(block, observations, insights, charts, usable, max_charts=remaining_chart_capacity)
                for block in slide.visual_blocks
            ]
            blocks = [b for b in blocks if b.chart_ids or b.observation_ids or b.insight_ids][:4]

            # Re-collect total chart IDs across slide and blocks capped at 3
            all_slide_charts: list[str] = list(chart_ids)
            for block in blocks:
                for cid in block.chart_ids:
                    if cid not in all_slide_charts and len(all_slide_charts) < 3:
                        all_slide_charts.append(cid)
                    elif cid not in all_slide_charts:
                        # Exceeded 3 charts across slide, remove from block
                        block.chart_ids = [c for c in block.chart_ids if c in all_slide_charts]

            referenced_pages = self._reference_pages(
                chart_ids, observation_ids, insight_ids, blocks, observations, insights, charts
            )

            if slide.slide_type == "company_overview":
                source_pages = (
                    sorted(set(slide.source_pages) & valid_pages)
                    if set(slide.source_pages) & valid_pages
                    else sorted(cleaned_company.source_pages or self._profile_pages(result))
                )
            elif slide.slide_type in {"executive_summary", "analysis", "risks"}:
                if referenced_pages:
                    matching = sorted(set(slide.source_pages) & referenced_pages)
                    source_pages = matching if matching else sorted(referenced_pages)
                else:
                    source_pages = sorted(set(slide.source_pages) & valid_pages)
            else:
                source_pages = sorted(set(slide.source_pages) & valid_pages)

            title = slide.title.strip() or self._default_title(slide.slide_type, ordinal)

            if slide.slide_type == "analysis":
                title = re.sub(r"(?i)^(?:add|less|plus|minus)\s*[:\-\u2013\u2014]\s*", "", title)
                title = re.sub(r"(?i)^(?:adjustments?|reconciliation|sub-?total|total)\s*[:\-\u2013\u2014]\s*", "", title)
                title = " ".join(title.split()).strip(" :;,-")
                if len(title) > 65 and not any(w in title.casefold() for w in ("trajectory", "trend", "movement", "growth", "performance", "increased", "decreased", "stable")):
                    title = sanitize_metric_for_title(title, max_length=55)
            elif slide.slide_type == "appendix":
                if any(w in title.casefold() for w in ("offering", "proceeds")):
                    has_offering = any("offering" in (o.metric_canonical or o.metric_original).casefold() or "proceeds" in (o.metric_canonical or o.metric_original).casefold() for o in observations.values())
                    if not has_offering:
                        title = "Key Data Appendix"
                if any(w in (slide.section_title or "").casefold() for w in ("offering", "proceeds")):
                    has_offering = any("offering" in (o.metric_canonical or o.metric_original).casefold() or "proceeds" in (o.metric_canonical or o.metric_original).casefold() for o in observations.values())
                    if not has_offering:
                        slide.section_title = "Appendix"
            title = polish_slide_title(title)
            message = slide.message.strip()
            bullets = [item.strip() for item in slide.bullets if item.strip()]

            if slide.slide_type in {"executive_summary", "analysis", "risks"}:
                allowed_numbers = self._allowed_numbers(
                    chart_ids, observation_ids, insight_ids, blocks, observations, insights, charts
                )
                if not self._numbers_supported(title, allowed_numbers):
                    title = self._default_title(slide.slide_type, ordinal)
                message = self._clean_sentences(message, allowed_numbers)
                bullets = [item for item in bullets if self._numbers_supported(item, allowed_numbers)]

            # Drop analysis/risks slides that have zero valid evidence references
            if slide.slide_type in {"analysis", "risks"} and not (
                chart_ids or observation_ids or insight_ids or any(b.chart_ids or b.observation_ids or b.insight_ids for b in blocks)
            ):
                continue

            layout = slide.layout
            # Check analysis slide data density: insight_ids alone cannot justify a standalone analysis slide
            if slide.slide_type == "analysis":
                has_chart = bool(chart_ids or any(b.chart_ids for b in blocks))
                effective_obs = [oid for oid in observation_ids]
                for b in blocks:
                    effective_obs.extend(b.observation_ids)
                effective_obs = list(dict.fromkeys(effective_obs))

                has_table = slide.layout in {"data_overview", "table_plus_kpis", "chart_with_data"} and len(effective_obs) >= 2
                has_obs = len(effective_obs) >= 2
                has_blocks = any(len(b.chart_ids) > 0 or len(b.observation_ids) >= 2 for b in blocks)
                is_sufficient = has_chart or has_table or has_obs or has_blocks

                if not is_sufficient:
                    # Resolution 1: Generate a small evidence table if sufficient structured observations exist
                    table_obs = self._find_observations_for_topic(title, insight_ids, insights, index)
                    if len(table_obs) >= 2:
                        observation_ids = [o.id for o in table_obs[:4]]
                        referenced_pages = self._reference_pages(
                            chart_ids, observation_ids, insight_ids, blocks, observations, insights, charts
                        )
                        source_pages = sorted(set(source_pages) | referenced_pages)
                        layout = "data_overview" if slide.layout in {"auto", "single"} else slide.layout
                        is_sufficient = True
                    else:
                        # Resolution 2: Merge into the most relevant neighbouring analysis slide if possible
                        existing_analysis = [s for s in repaired_slides if s.slide_type == "analysis"]
                        if existing_analysis:
                            # Prefer same section or immediate previous analysis slide
                            target = next(
                                (s for s in reversed(existing_analysis) if s.section_id == section_id),
                                existing_analysis[-1],
                            )
                            target.insight_ids = list(dict.fromkeys([*target.insight_ids, *insight_ids]))
                            if message and message != target.message and message not in target.bullets:
                                target.bullets = [*target.bullets, message][:5]
                            for b in bullets:
                                if b not in target.bullets:
                                    target.bullets = [*target.bullets, b][:5]
                            if observation_ids:
                                target.observation_ids = list(dict.fromkeys([*target.observation_ids, *observation_ids]))
                            target.source_pages = sorted(set(target.source_pages) | set(source_pages))
                            continue
                        else:
                            # Resolution 3: Queue for merging into the next valid analysis slide, or omit
                            pending_under_supported.append((insight_ids, message, bullets, source_pages, observation_ids, section_id))
                            continue

                # If this analysis slide is valid and there are pending under-supported insights from preceding slides, merge them here
                if pending_under_supported:
                    for p_ins, p_msg, p_bul, p_pages, p_obs, _ in pending_under_supported:
                        insight_ids = list(dict.fromkeys([*insight_ids, *p_ins]))
                        if p_msg and p_msg != message and p_msg not in bullets:
                            bullets = [*bullets, p_msg][:5]
                        for b in p_bul:
                            if b not in bullets:
                                bullets = [*bullets, b][:5]
                        observation_ids = list(dict.fromkeys([*observation_ids, *p_obs]))
                        source_pages = sorted(set(source_pages) | set(p_pages))
                    pending_under_supported.clear()

            if slide.slide_type == "analysis" and not message:
                message = "Evidence-backed comparison of retained reported values."

            section_title = slide.section_title.strip()
            if slide.slide_type == "analysis" and not section_title:
                section_title = "Analysis"
            elif slide.slide_type == "risks" and not section_title:
                section_title = "Key watch items"
            elif slide.slide_type == "data_quality" and not section_title:
                section_title = "Data quality"
            elif slide.slide_type == "appendix" and not section_title:
                section_title = "Appendix"

            section_id = slide.section_id.strip() or (
                f"analysis_{ordinal}" if slide.slide_type == "analysis" else slide.slide_type
            )

            repaired_slides.append(
                PresentationSlide(
                    id=slide.id.strip() or stable_id("slide", slide.slide_type, ordinal),
                    slide_type=slide.slide_type,
                    title=title,
                    section_id=section_id,
                    section_title=section_title,
                    slide_role=slide.slide_role,
                    layout=layout,
                    message=message,
                    bullets=bullets[:5],
                    chart_ids=chart_ids,
                    observation_ids=observation_ids,
                    insight_ids=insight_ids,
                    visual_blocks=blocks,
                    source_pages=source_pages,
                )
            )

        if pending_under_supported:
            final_analysis = [s for s in repaired_slides if s.slide_type == "analysis"]
            if final_analysis:
                target = final_analysis[-1]
                for p_ins, p_msg, p_bul, p_pages, p_obs, _ in pending_under_supported:
                    target.insight_ids = list(dict.fromkeys([*target.insight_ids, *p_ins]))
                    if p_msg and p_msg != target.message and p_msg not in target.bullets:
                        target.bullets = [*target.bullets, p_msg][:5]
                    for b in p_bul:
                        if b not in target.bullets:
                            target.bullets = [*target.bullets, b][:5]
                    target.source_pages = sorted(set(target.source_pages) | set(p_pages))
            elif any(p_obs for _, _, _, _, p_obs, _ in pending_under_supported):
                all_ins = [ins for p_ins, _, _, _, _, _ in pending_under_supported for ins in p_ins]
                all_obs = [obs for _, _, _, _, p_obs, _ in pending_under_supported for obs in p_obs]
                all_pages = [page for _, _, _, p_pages, _, _ in pending_under_supported for page in p_pages]
                first_msg = next((msg for _, msg, _, _, _, _ in pending_under_supported if msg), "Evidence-backed analysis.")
                all_buls = [b for _, _, buls, _, _, _ in pending_under_supported for b in buls][:5]
                repaired_slides.append(
                    PresentationSlide(
                        id=stable_id("slide", "analysis", 1),
                        slide_type="analysis",
                        title="Key Analysis",
                        section_id="analysis_1",
                        section_title="Analysis",
                        layout="data_overview" if len(all_obs) >= 2 else "auto",
                        message=first_msg,
                        bullets=all_buls,
                        observation_ids=list(dict.fromkeys(all_obs)),
                        insight_ids=list(dict.fromkeys(all_ins)),
                        source_pages=sorted(set(all_pages)),
                    )
                )
            pending_under_supported.clear()

        # Backfill analysis slides if AI analysis slides were lost or empty despite usable charts
        repaired_analysis = [s for s in repaired_slides if s.slide_type == "analysis"]
        referenced_chart_ids = {
            cid
            for s in repaired_analysis
            for cid in (*s.chart_ids, *(c for b in s.visual_blocks for c in b.chart_ids))
            if cid in charts
        }

        if usable and (not repaired_analysis or not referenced_chart_ids):
            chart_groups = _group_chart_plans(usable[:10], index)
            backfilled_slides: list[PresentationSlide] = []
            for g_idx, group in enumerate(chart_groups, start=1):
                g_chart_ids = [c.id for c in group]
                g_pages = sorted({p for c in group for p in c.source_pages})
                obs_first = next((index.get(oid) for oid in group[0].observation_ids if index.get(oid)), None)
                first_label = display_metric_name(obs_first) if obs_first else group[0].title.replace(" — Reported Values", "")
                group_title = _chart_group_title(group, index)
                layout = "single" if len(group) == 1 else "two_up" if len(group) == 2 else "three_up"
                blocks = [
                    PresentationVisualBlock(
                        role="hero" if i == 0 else "supporting",
                        title=(
                            display_metric_name(next((index.get(oid) for oid in c.observation_ids if index.get(oid)), None))
                            or c.title.replace(" — Reported Values", "")
                        ),
                        chart_ids=[c.id],
                    )
                    for i, c in enumerate(group)
                ]
                clean_title = sanitize_metric_for_title(re.sub(r"(?i)\s+and\s+related\s+measures\b", "", group_title).strip(), max_length=48)
                clean_title = re.sub(r"(?i)\s+analysis\b", "", clean_title).strip()
                slide_title = polish_slide_title(clean_title if len(clean_title.split()) >= 2 else f"{clean_title} Overview")
                backfilled_slides.append(
                    PresentationSlide(
                        id=f"slide_analysis_{g_idx}",
                        slide_type="analysis",
                        title=slide_title,
                        section_id=f"analysis_{g_idx}",
                        section_title=first_label,
                        slide_role="overview" if g_idx == 1 else "deep_dive",
                        layout=layout,
                        message="Evidence-backed comparison of retained reported values.",
                        chart_ids=g_chart_ids,
                        visual_blocks=blocks,
                        source_pages=g_pages,
                    )
                )
            repaired_slides.extend(backfilled_slides)
        elif usable and len(referenced_chart_ids) < min(len(usable), 4):
            remaining_charts = [c for c in usable[:10] if c.id not in referenced_chart_ids]
            if remaining_charts:
                chart_groups = _group_chart_plans(remaining_charts, index)
                start_idx = len(repaired_analysis) + 1
                for g_idx, group in enumerate(chart_groups, start=start_idx):
                    g_chart_ids = [c.id for c in group]
                    g_pages = sorted({p for c in group for p in c.source_pages})
                    obs_first = next((index.get(oid) for oid in group[0].observation_ids if index.get(oid)), None)
                    first_label = display_metric_name(obs_first) if obs_first else group[0].title.replace(" — Reported Values", "")
                    group_title = _chart_group_title(group, index)
                    layout = "single" if len(group) == 1 else "two_up" if len(group) == 2 else "three_up"
                    blocks = [
                        PresentationVisualBlock(
                            role="hero" if i == 0 else "supporting",
                            title=(
                                display_metric_name(next((index.get(oid) for oid in c.observation_ids if index.get(oid)), None))
                                or c.title.replace(" — Reported Values", "")
                            ),
                            chart_ids=[c.id],
                        )
                        for i, c in enumerate(group)
                    ]
                    clean_title2 = sanitize_metric_for_title(re.sub(r"(?i)\s+and\s+related\s+measures\b", "", group_title).strip(), max_length=48)
                    clean_title2 = re.sub(r"(?i)\s+analysis\b", "", clean_title2).strip()
                    slide_title2 = polish_slide_title(clean_title2 if len(clean_title2.split()) >= 2 else f"{clean_title2} Overview")
                    repaired_slides.append(
                        PresentationSlide(
                            id=f"slide_analysis_{g_idx}",
                            slide_type="analysis",
                            title=slide_title2,
                            section_id=f"analysis_{g_idx}",
                            section_title=first_label,
                            slide_role="deep_dive",
                            layout=layout,
                            message="Evidence-backed comparison of retained reported values.",
                            chart_ids=g_chart_ids,
                            visual_blocks=blocks,
                            source_pages=g_pages,
                        )
                    )

        has_analytical_evidence = bool(
            result.charts
            or result.analysis_results
            or len([o for o in result.observations if o.value is not None]) >= 2
        )
        if not any(s.slide_type == "analysis" for s in repaired_slides) and has_analytical_evidence:
            valid_obs = [o for o in result.observations if o.value is not None and o.evidence][:6]
            obs_pages = sorted({source.page for o in valid_obs for source in o.evidence}) or self._profile_pages(result)
            repaired_slides.append(
                PresentationSlide(
                    id="slide_analysis_1",
                    slide_type="analysis",
                    title="Key Reported Evidence",
                    section_id="analysis_1",
                    section_title="Evidence",
                    slide_role="overview",
                    layout="single",
                    message="Evidence-backed comparison of retained reported values.",
                    observation_ids=[o.id for o in valid_obs],
                    visual_blocks=[
                        PresentationVisualBlock(
                            role="hero",
                            title="Reported Observations",
                            observation_ids=[o.id for o in valid_obs],
                        )
                    ],
                    source_pages=obs_pages,
                )
            )

        # Merge duplicate risks vs executive summary language
        self._deduplicate_risks_vs_summary(repaired_slides)

        ordered_plan = self._normalise_structure(
            PresentationPlan(
                title=plan.title.strip() or result.report_plan.title,
                report_type=plan.report_type.strip() or "Document analysis",
                company=cleaned_company,
                slides=repaired_slides,
            ),
            result,
        )

        return PresentationPlanValidator().validate(ordered_plan, result)

    @classmethod
    def _resolve_chart_ids(
        cls,
        raw_ids: list[str],
        title: str,
        charts: dict[str, ChartPlan],
        usable_charts: list[ChartPlan],
    ) -> list[str]:
        resolved: list[str] = []
        chart_by_num: dict[int, str] = {}
        for idx, chart in enumerate(usable_charts):
            chart_by_num[idx + 1] = chart.id
            chart_by_num[idx] = chart.id

        normalized_charts: dict[str, str] = {}
        for c in usable_charts:
            normalized_charts[cls._normalized_text(c.title)] = c.id
            if c.analysis_task_id:
                normalized_charts[cls._normalized_text(c.analysis_task_id)] = c.id
            normalized_charts[cls._normalized_text(c.id)] = c.id

        for raw in raw_ids:
            if raw in charts:
                resolved.append(raw)
                continue
            norm = cls._normalized_text(raw)
            if norm in normalized_charts:
                resolved.append(normalized_charts[norm])
                continue
            # Match 1-based and 0-based indices like "chart_1", "chart-1", "1"
            num_match = re.search(r"\b(\d+)\b", raw)
            if num_match:
                num = int(num_match.group(1))
                if num in chart_by_num:
                    resolved.append(chart_by_num[num])
                    continue
            for norm_key, cid in normalized_charts.items():
                if norm and len(norm) >= 4 and (norm in norm_key or norm_key in norm):
                    resolved.append(cid)
                    break

        if not resolved and title.strip():
            norm_title = cls._normalized_text(title)
            ignored_tokens = {
                "cost", "costs", "profit", "profits", "expense", "expenses", "revenue",
                "loss", "losses", "income", "net", "gross", "financial", "operating",
                "trajectory", "analysis", "trend", "chart", "values", "reported", "and", "the",
            }
            title_tokens = {t for t in norm_title.split() if len(t) >= 3 and t not in ignored_tokens}
            for norm_key, cid in normalized_charts.items():
                if norm_key:
                    key_tokens = {t for t in norm_key.split() if len(t) >= 3 and t not in ignored_tokens}
                    if title_tokens and key_tokens and (title_tokens & key_tokens):
                        resolved.append(cid)
                        break

        return cls._unique(resolved)

    @classmethod
    def _clean_block(
        cls,
        block: PresentationVisualBlock,
        observations: dict[str, object],
        insights: dict[str, object],
        charts: dict[str, ChartPlan],
        usable_charts: list[ChartPlan],
        *,
        max_charts: int = 2,
    ) -> PresentationVisualBlock:
        resolved_chart_ids = cls._resolve_chart_ids(block.chart_ids, block.title, charts, usable_charts)
        chart_ids = resolved_chart_ids[:max_charts]
        observation_ids = cls._unique([item for item in block.observation_ids if item in observations])[:12]
        insight_ids = cls._unique([item for item in block.insight_ids if item in insights])[:3]
        chart_type = block.chart_type
        if chart_type == "table":
            chart_type = None
        elif chart_type and any(
            chart_type not in {*charts[cid].available_chart_types, charts[cid].chart_type}
            for cid in chart_ids
            if cid in charts
        ):
            chart_type = None
        return PresentationVisualBlock(
            role=block.role,
            title=block.title.strip(),
            chart_ids=chart_ids,
            observation_ids=observation_ids,
            insight_ids=insight_ids,
            chart_type=chart_type,
        )

    def _clean_sentences(self, text: str, allowed: set[str]) -> str:
        if not text.strip():
            return ""
        sentences = self._sentence_split.split(text.strip())
        if len(sentences) <= 1:
            return text.strip() if self._numbers_supported(text.strip(), allowed) else ""
        valid_sentences = [s.strip() for s in sentences if s.strip() and self._numbers_supported(s.strip(), allowed)]
        return " ".join(valid_sentences)

    @classmethod
    def _clean_company(cls, company: CompanyProfile, result: PipelineResult, valid_pages: set[int]) -> CompanyProfile:
        def dedupe(values: list[str]) -> list[str]:
            seen: set[str] = set()
            out: list[str] = []
            for item in values:
                norm = cls._normalized_text(item)
                if norm and norm not in seen:
                    seen.add(norm)
                    out.append(item.strip())
            return out[:6]

        pages = sorted(set(company.source_pages) & valid_pages)
        company_pages = set(pages) | {p for fact in company.key_facts for p in fact.source_pages if p in valid_pages}
        allowed_company_numbers = PresentationPlanValidator._allowed_company_numbers(company_pages, result)

        facts: list[CompanyFact] = []
        seen: set[str] = set()
        for fact in company.key_facts:
            label = fact.label.strip()
            key = cls._normalized_text(label)
            fact_pages = sorted(set(fact.source_pages) & valid_pages)
            fact_allowed = (
                PresentationPlanValidator._allowed_company_numbers(set(fact_pages), result)
                if fact_pages
                else allowed_company_numbers
            )
            val = fact.value.strip()
            if label and key not in seen and cls._numbers_supported(val, fact_allowed):
                facts.append(
                    fact.model_copy(
                        update={
                            "label": label,
                            "value": val,
                            "source_pages": fact_pages,
                        }
                    )
                )
                seen.add(key)

        one_line = company.one_line_description.strip()
        if not cls._numbers_supported(one_line, allowed_company_numbers):
            sentences = cls._sentence_split.split(one_line)
            valid_s = [s.strip() for s in sentences if s.strip() and cls._numbers_supported(s.strip(), allowed_company_numbers)]
            one_line = " ".join(valid_s)

        business_model = company.business_model.strip()
        if not cls._numbers_supported(business_model, allowed_company_numbers):
            sentences = cls._sentence_split.split(business_model)
            valid_s = [s.strip() for s in sentences if s.strip() and cls._numbers_supported(s.strip(), allowed_company_numbers)]
            business_model = " ".join(valid_s)

        track_record = (
            company.track_record_period.strip()
            if cls._numbers_supported(company.track_record_period.strip(), allowed_company_numbers)
            else ""
        )

        has_content = any(
            (
                company.name,
                one_line,
                company.industry,
                company.headquarters,
                company.listing_market,
                track_record,
                business_model,
                facts,
                company.products,
                company.application_areas,
                company.segments,
                company.geographies,
            )
        )
        if has_content and not (pages or any(fact.source_pages for fact in facts)):
            return CompanyProfile()
        return company.model_copy(
            update={
                "one_line_description": one_line,
                "business_model": business_model,
                "track_record_period": track_record,
                "products": dedupe(company.products),
                "application_areas": dedupe(company.application_areas),
                "segments": dedupe(company.segments),
                "geographies": dedupe(company.geographies),
                "key_facts": facts[:8],
                "source_pages": pages,
            }
        )

    @classmethod
    def _deduplicate_risks_vs_summary(cls, slides: list[PresentationSlide]) -> None:
        summaries = [s for s in slides if s.slide_type == "executive_summary"]
        risks = [s for s in slides if s.slide_type == "risks"]
        if not summaries or not risks:
            return
        summary = summaries[0]
        risk = risks[0]
        summary_texts = {
            cls._normalized_text(t)
            for t in (summary.message, *summary.bullets)
            if t.strip()
        }
        # Deduplicate internal risk bullets
        deduped_bullets: list[str] = []
        seen_risk: set[str] = set()
        for b in risk.bullets:
            norm = cls._normalized_text(b)
            if norm and norm not in summary_texts and norm not in seen_risk:
                seen_risk.add(norm)
                deduped_bullets.append(b)
        risk.bullets = deduped_bullets
        if cls._normalized_text(risk.message) in summary_texts:
            risk.message = "Key areas of ongoing monitoring identified in the source materials."

    def _normalise_structure(self, plan: PresentationPlan, result: PipelineResult) -> PresentationPlan:
        """Enforce required slide order and presence of essential slides."""
        required = ("cover", "company_overview", "executive_summary")
        by_type: dict[str, list[PresentationSlide]] = defaultdict(list)
        for slide in plan.slides:
            by_type[slide.slide_type].append(slide)

        ordered: list[PresentationSlide] = []
        for slide_type in required:
            if by_type[slide_type]:
                ordered.append(by_type[slide_type][0])
            else:
                ordered.append(self._fallback_for_type(slide_type, result))

        ordered.extend(by_type["analysis"][:14])
        has_analytical_evidence = bool(
            result.charts
            or result.analysis_results
            or len([o for o in result.observations if o.value is not None]) >= 2
        )
        if not by_type["analysis"] and has_analytical_evidence:
            ordered.append(self._fallback_for_type("analysis", result))

        if by_type["risks"]:
            # Ensure risk slide has evidence
            risk_slide = by_type["risks"][0]
            if risk_slide.chart_ids or risk_slide.observation_ids or risk_slide.insight_ids or risk_slide.visual_blocks:
                ordered.append(risk_slide)

        ordered.append(
            by_type["data_quality"][0]
            if by_type["data_quality"]
            else self._fallback_for_type("data_quality", result)
        )
        ordered.append(
            by_type["appendix"][0]
            if by_type["appendix"]
            else self._fallback_for_type("appendix", result)
        )

        seen_ids: set[str] = set()
        for ordinal, slide in enumerate(ordered):
            if slide.id in seen_ids:
                slide.id = stable_id("slide", slide.slide_type, ordinal)
            seen_ids.add(slide.id)

        return plan.model_copy(update={"slides": ordered})

    def _fallback_for_type(self, slide_type: str, result: PipelineResult) -> PresentationSlide:
        pages = self._profile_pages(result)
        if slide_type == "cover":
            return PresentationSlide(id="slide_cover", slide_type="cover", title=result.report_plan.title)
        if slide_type == "analysis":
            from adaptive_document_agent.services.pptx_export import _usable_charts
            usable = _usable_charts(result)
            if usable:
                c = usable[0]
                title = c.title.replace(" — Reported Values", "").replace(" - Reported Values", "")
                return PresentationSlide(
                    id="slide_analysis_1",
                    slide_type="analysis",
                    title=f"{title} Analysis",
                    section_id="analysis_1",
                    section_title="Analysis",
                    slide_role="overview",
                    layout="single",
                    message="Evidence-backed comparison of retained reported values.",
                    chart_ids=[c.id],
                    source_pages=c.source_pages,
                )
            valid_obs = [o for o in result.observations if o.value is not None and o.evidence][:6]
            return PresentationSlide(
                id="slide_analysis_1",
                slide_type="analysis",
                title="Evidence Analysis",
                section_id="analysis_1",
                section_title="Analysis",
                slide_role="overview",
                layout="single",
                message="Evidence-backed comparison of retained reported values.",
                observation_ids=[o.id for o in valid_obs],
                source_pages=sorted({source.page for o in valid_obs for source in o.evidence}) or pages,
            )
        if slide_type == "company_overview":
            return PresentationSlide(
                id="slide_company_overview",
                slide_type="company_overview",
                title="Document at a Glance",
                source_pages=pages,
            )
        if slide_type == "executive_summary":
            insights = sorted(
                (item for item in result.insights if item.evidence),
                key=lambda item: (item.importance, item.confidence),
                reverse=True,
            )[:5]
            return PresentationSlide(
                id="slide_executive_summary",
                slide_type="executive_summary",
                title="Executive Summary",
                section_id="executive_summary",
                section_title="Executive summary",
                slide_role="overview",
                message="Key retained findings selected from the source document.",
                insight_ids=[item.id for item in insights],
                source_pages=sorted({source.page for item in insights for source in item.evidence}),
            )
        if slide_type == "data_quality":
            return PresentationSlide(
                id="slide_data_quality",
                slide_type="data_quality",
                title="Data Quality and Scope",
                section_id="data_quality",
                section_title="Data quality",
                slide_role="methodology",
                source_pages=pages,
            )
        return PresentationSlide(
            id="slide_appendix",
            slide_type="appendix",
            title="Source Data Appendix",
            section_id="appendix",
            section_title="Appendix",
            slide_role="source_data",
        )

    @staticmethod
    def _profile_pages(result: PipelineResult) -> list[int]:
        pages = [p for p in result.profile.document_summary_pages if 1 <= p <= result.document.page_count]
        if not pages and result.document.page_count >= 1:
            pages = [1]
        return pages[:6]

    @classmethod
    def _reference_pages(
        cls,
        chart_ids: list[str],
        observation_ids: list[str],
        insight_ids: list[str],
        blocks: list[PresentationVisualBlock],
        observations: dict[str, object],
        insights: dict[str, object],
        charts: dict[str, object],
    ) -> set[int]:
        pages: set[int] = set()
        all_charts = {*chart_ids, *(cid for b in blocks for cid in b.chart_ids)}
        all_observations = {*observation_ids, *(oid for b in blocks for oid in b.observation_ids)}
        all_insights = {*insight_ids, *(iid for b in blocks for iid in b.insight_ids)}
        for oid in all_observations:
            if oid in observations:
                pages.update(source.page for source in observations[oid].evidence)
        for iid in all_insights:
            if iid in insights:
                pages.update(source.page for source in insights[iid].evidence)
        for cid in all_charts:
            if cid in charts:
                pages.update(charts[cid].source_pages)
                for oid in charts[cid].observation_ids:
                    if oid in observations:
                        pages.update(source.page for source in observations[oid].evidence)
        return pages

    @classmethod
    def _allowed_numbers(
        cls,
        chart_ids: list[str],
        observation_ids: list[str],
        insight_ids: list[str],
        blocks: list[PresentationVisualBlock],
        observations: dict[str, object],
        insights: dict[str, object],
        charts: dict[str, object],
    ) -> set[str]:
        all_oids = {*observation_ids, *(oid for b in blocks for oid in b.observation_ids)}
        for cid in {*chart_ids, *(c for b in blocks for c in b.chart_ids)}:
            if cid in charts:
                all_oids.update(charts[cid].observation_ids)
        text_parts = [
            str(v)
            for oid in all_oids
            if oid in observations
            for v in (
                observations[oid].value,
                observations[oid].raw_value,
                observations[oid].period,
                observations[oid].entity,
                observations[oid].dimensions,
            )
            if v is not None
        ]
        all_iids = {*insight_ids, *(iid for b in blocks for iid in b.insight_ids)}
        for iid in all_iids:
            if iid in insights:
                text_parts.extend((insights[iid].title, insights[iid].narrative))
        return PresentationPlanValidator._numbers(" ".join(text_parts))

    @classmethod
    def _numbers_supported(cls, value: str, allowed: set[str]) -> bool:
        return not cls._numeric_claim.search(value) or PresentationPlanValidator._numbers(value) <= allowed

    @classmethod
    def _unique(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))

    @classmethod
    def _normalized_text(cls, value: str) -> str:
        return " ".join(re.sub(r"[^a-z0-9%]+", " ", value.casefold()).split())

    @staticmethod
    def _default_title(slide_type: str, ordinal: int = 0) -> str:
        return {
            "cover": "Document Analysis",
            "company_overview": "Document at a Glance",
            "executive_summary": "Executive Summary",
            "analysis": "Evidence Analysis",
            "risks": "Key Watch Items",
            "data_quality": "Data Quality and Scope",
            "appendix": "Source Data Appendix",
        }.get(slide_type, "Analysis")

    @staticmethod
    def _find_observations_for_topic(
        title: str,
        insight_ids: list[str],
        insights: dict[str, object],
        index: object,
    ) -> list[object]:
        from adaptive_document_agent.document_model.topic_matcher import extract_topic_tokens

        candidate_metrics: list[str] = []
        for iid in insight_ids:
            ins = insights.get(iid)
            if ins:
                m = getattr(ins, "metric", None)
                if m:
                    candidate_metrics.append(m)
        title_tokens = extract_topic_tokens(title)
        if hasattr(index, "metrics"):
            for m in index.metrics():
                m_tokens = extract_topic_tokens(m)
                if m_tokens and (m_tokens.issubset(title_tokens) or title_tokens.issubset(m_tokens)):
                    candidate_metrics.append(m)

        for metric in candidate_metrics:
            obs = index.for_metric(metric) if hasattr(index, "for_metric") else []
            valid_obs = [o for o in obs if getattr(o, "value", None) is not None]
            if len(valid_obs) >= 2:
                return valid_obs
        return []
