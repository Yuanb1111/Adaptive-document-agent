"""Deterministic safety checks for AI-authored presentation plans."""

from collections import Counter
import re

from adaptive_document_agent.models import PipelineResult, PresentationPlan


class PresentationPlanValidator:
    """Reject plans that exceed scope or reference facts the pipeline did not retain."""

    _required_types = {"cover", "company_overview", "executive_summary", "data_quality", "appendix"}

    def validate(self, plan: PresentationPlan, result: PipelineResult) -> PresentationPlan:
        errors: list[str] = []
        slide_ids = [slide.id for slide in plan.slides]
        if len(slide_ids) != len(set(slide_ids)):
            errors.append("slide IDs must be unique")

        type_counts = Counter(slide.slide_type for slide in plan.slides)
        for slide_type in sorted(self._required_types):
            if type_counts[slide_type] != 1:
                errors.append(f"the plan must contain exactly one {slide_type} slide")
        if type_counts["risks"] > 1:
            errors.append("the plan may contain at most one risks slide")

        expected_prefix = ["cover", "company_overview", "executive_summary"]
        actual_prefix = [slide.slide_type for slide in plan.slides[:3]]
        if actual_prefix != expected_prefix:
            errors.append("the first three slides must be cover, company_overview, and executive_summary")
        if plan.slides and plan.slides[-1].slide_type != "appendix":
            errors.append("the appendix slide must be last")
        if type_counts["data_quality"] == 1 and type_counts["appendix"] == 1:
            quality_index = next(index for index, slide in enumerate(plan.slides) if slide.slide_type == "data_quality")
            appendix_index = next(index for index, slide in enumerate(plan.slides) if slide.slide_type == "appendix")
            if quality_index > appendix_index:
                errors.append("data quality must appear before the appendix")
        slide_order = {
            "cover": 0,
            "company_overview": 1,
            "executive_summary": 2,
            "analysis": 3,
            "risks": 4,
            "data_quality": 5,
            "appendix": 6,
        }
        ranks = [slide_order[slide.slide_type] for slide in plan.slides]
        if ranks != sorted(ranks):
            errors.append("slide types do not follow the required narrative order")

        main_slide_count = sum(slide.slide_type != "appendix" for slide in plan.slides)
        if main_slide_count > 18:
            errors.append("the main presentation may contain at most 18 planned slides")

        observation_by_id = {item.id: item for item in result.observations}
        insight_by_id = {item.id: item for item in result.insights}
        chart_by_id = {item.id: item for item in result.charts}
        valid_pages = set(range(1, result.document.page_count + 1))

        company_pages = {*plan.company.source_pages}
        company_pages.update(page for fact in plan.company.key_facts for page in fact.source_pages)
        if company_pages - valid_pages:
            errors.append("company profile contains source pages outside the document")
        company_has_content = any(
            value.strip()
            for value in (
                plan.company.name,
                plan.company.one_line_description,
                plan.company.industry,
                plan.company.headquarters,
                plan.company.listing_market,
                plan.company.track_record_period,
                plan.company.business_model,
            )
        ) or bool(plan.company.products or plan.company.segments or plan.company.geographies or plan.company.key_facts)
        if company_has_content and not company_pages:
            errors.append("company profile content must cite at least one source page")
        for label, values in (
            ("products", plan.company.products),
            ("segments", plan.company.segments),
            ("geographies", plan.company.geographies),
        ):
            normalized = [self._normalized_text(value) for value in values if value.strip()]
            if len(normalized) != len(set(normalized)):
                errors.append(f"company profile contains duplicate {label}")
        fact_labels = [self._normalized_text(item.label) for item in plan.company.key_facts if item.label.strip()]
        if len(fact_labels) != len(set(fact_labels)):
            errors.append("company profile contains duplicate key-fact labels")

        allowed_company_numbers = self._allowed_company_numbers(set(plan.company.source_pages) & valid_pages, result)
        company_fields_to_check = [
            ("one_line_description", plan.company.one_line_description),
            ("track_record_period", plan.company.track_record_period),
            ("business_model", plan.company.business_model),
            ("industry", plan.company.industry),
            ("headquarters", plan.company.headquarters),
            ("listing_market", plan.company.listing_market),
            ("offering_type", plan.company.offering_type),
            ("reporting_currency", plan.company.reporting_currency),
            *[(f"product {i+1}", p) for i, p in enumerate(plan.company.products)],
            *[(f"segment {i+1}", s) for i, s in enumerate(plan.company.segments)],
            *[(f"geography {i+1}", g) for i, g in enumerate(plan.company.geographies)],
        ]
        for field_label, field_val in company_fields_to_check:
            if field_val.strip():
                claimed = self._numbers(field_val)
                unsupported = claimed - allowed_company_numbers
                if unsupported:
                    errors.append(f"company profile field '{field_label}' contains unsupported numeric claims: {sorted(unsupported)}")

        for fact in plan.company.key_facts:
            fact_pages = set(fact.source_pages) & valid_pages or (set(plan.company.source_pages) & valid_pages)
            allowed_fact = self._allowed_company_numbers(fact_pages, result)
            claimed_fact = self._numbers(fact.value)
            unsupported_fact = claimed_fact - allowed_fact
            if unsupported_fact:
                errors.append(f"company fact '{fact.label}' contains unsupported numeric claims: {sorted(unsupported_fact)}")

        has_charts = bool(result.charts)
        has_analysis_results = any(item.result is not None and item.evidence for item in result.analysis_results)
        comparable_observations = [item for item in result.observations if item.evidence and item.value is not None]
        has_comparable_obs = len(comparable_observations) >= 2
        has_analytical_evidence = has_charts or has_analysis_results or has_comparable_obs

        analysis_slides = [slide for slide in plan.slides if slide.slide_type == "analysis"]
        if has_analytical_evidence and not analysis_slides:
            errors.append("the plan must contain at least one analysis slide when analytical evidence is present")

        if has_charts:
            referenced_charts = {
                cid
                for slide in analysis_slides
                for cid in (*slide.chart_ids, *(c for b in slide.visual_blocks for c in b.chart_ids))
            }
            if not any(cid in chart_by_id for cid in referenced_charts):
                errors.append("the plan must reference at least one available chart in an analysis slide when charts exist")
        elif has_analytical_evidence:
            referenced_evidence = {
                oid
                for slide in analysis_slides
                for oid in (
                    *slide.observation_ids,
                    *slide.insight_ids,
                    *(o for b in slide.visual_blocks for o in b.observation_ids),
                    *(i for b in slide.visual_blocks for i in b.insight_ids),
                )
            }
            valid_evidence_ids = {*observation_by_id.keys(), *insight_by_id.keys()}
            if not any(eid in valid_evidence_ids for eid in referenced_evidence):
                errors.append(
                    "at least one analysis slide must reference an observation or insight when analytical evidence is present"
                )

        for slide in plan.slides:
            observation_ids = {
                *slide.observation_ids,
                *(identifier for block in slide.visual_blocks for identifier in block.observation_ids),
            }
            insight_ids = {
                *slide.insight_ids,
                *(identifier for block in slide.visual_blocks for identifier in block.insight_ids),
            }
            chart_ids = {
                *slide.chart_ids,
                *(identifier for block in slide.visual_blocks for identifier in block.chart_ids),
            }
            unknown_observations = observation_ids - observation_by_id.keys()
            unknown_insights = insight_ids - insight_by_id.keys()
            unknown_charts = chart_ids - chart_by_id.keys()
            if unknown_observations:
                errors.append(f"slide {slide.id} references unknown observations: {sorted(unknown_observations)}")
            if unknown_insights:
                errors.append(f"slide {slide.id} references unknown insights: {sorted(unknown_insights)}")
            if unknown_charts:
                errors.append(f"slide {slide.id} references unknown charts: {sorted(unknown_charts)}")
            if set(slide.source_pages) - valid_pages:
                errors.append(f"slide {slide.id} contains source pages outside the document")
            if slide.slide_type in {"analysis", "risks"} and not (chart_ids or observation_ids or insight_ids):
                errors.append(f"slide {slide.id} has no retained evidence references")
            if slide.slide_type == "analysis":
                has_chart = bool(chart_ids or any(b.chart_ids for b in slide.visual_blocks))
                effective_obs = {*observation_ids, *(o for b in slide.visual_blocks for o in b.observation_ids)}
                has_table = slide.layout in {"data_overview", "table_plus_kpis", "chart_with_data"} and len(effective_obs) >= 2
                has_obs = len(effective_obs) >= 2
                has_blocks = any(b.chart_ids or len(b.observation_ids) >= 2 for b in slide.visual_blocks)
                if not (has_chart or has_table or has_obs or has_blocks) and not effective_obs:
                    errors.append(
                        f"analysis slide {slide.id} has insufficient data density: insight_ids alone do not justify "
                        "an analysis slide. Must include a chart, data table, at least 2 structured observations, "
                        "or a meaningful visual block."
                    )
            if slide.slide_type == "analysis" and not slide.message.strip():
                errors.append(f"analysis slide {slide.id} must state one message")
            if slide.slide_type == "analysis":
                for pattern in (
                    r"(?i)\bunaudited\s+analysis\b",
                    r"(?i)\btrend\s+and\s+related\s+measures\b",
                    r"(?i)\bevidence-?backed\s+comparison\b",
                    r"(?i)\bretained\s+reported\s+values\b",
                ):
                    if re.search(pattern, slide.title):
                        errors.append(
                            f"analysis slide {slide.id} has a generic blacklisted title: '{slide.title}'. "
                            "Titles must state the main supported takeaway or direction."
                        )
                        break
                block_titles = [b.title.strip().casefold() for b in slide.visual_blocks if b.title.strip()]
                if len(block_titles) > 1 and len(block_titles) != len(set(block_titles)):
                    errors.append(f"analysis slide {slide.id} has duplicate card/block titles: {block_titles}")
            if slide.slide_type in {"analysis", "risks"} and not slide.section_title.strip():
                errors.append(f"slide {slide.id} must provide a concise section_title")
            if len(chart_ids) > 3:
                errors.append(f"slide {slide.id} may contain at most three charts")
            for block in slide.visual_blocks:
                if block.chart_type:
                    if block.chart_type == "table":
                        errors.append(
                            f"slide {slide.id} must use observation_ids for exact-data blocks instead of chart_type table"
                        )
                    for identifier in block.chart_ids:
                        chart = chart_by_id.get(identifier)
                        if chart and block.chart_type not in {*chart.available_chart_types, chart.chart_type}:
                            errors.append(
                                f"slide {slide.id} requests unsupported chart type {block.chart_type} for {identifier}"
                            )

            referenced_pages: set[int] = set()
            referenced_observation_ids = set(observation_ids)
            for identifier in observation_ids:
                item = observation_by_id.get(identifier)
                if item:
                    referenced_pages.update(source.page for source in item.evidence)
            for identifier in insight_ids:
                item = insight_by_id.get(identifier)
                if item:
                    referenced_pages.update(source.page for source in item.evidence)
            for identifier in chart_ids:
                item = chart_by_id.get(identifier)
                if item:
                    referenced_pages.update(item.source_pages)
                    referenced_observation_ids.update(item.observation_ids)
                    for observation_id in item.observation_ids:
                        observation = observation_by_id.get(observation_id)
                        if observation:
                            referenced_pages.update(source.page for source in observation.evidence)
            if (
                slide.slide_type != "company_overview"
                and referenced_pages
                and set(slide.source_pages) - referenced_pages
            ):
                errors.append(f"slide {slide.id} cites pages not supported by its retained references")
            if slide.slide_type in {"executive_summary", "analysis", "risks"} and referenced_pages and not slide.source_pages:
                errors.append(f"slide {slide.id} must cite its retained evidence pages")

            if slide.slide_type in {"executive_summary", "analysis", "risks"}:
                allowed_text_parts: list[str] = []
                for identifier in referenced_observation_ids:
                    item = observation_by_id.get(identifier)
                    if item:
                        allowed_text_parts.extend(
                            str(value)
                            for value in (item.value, item.raw_value, item.period, item.entity, item.dimensions)
                            if value is not None
                        )
                for identifier in insight_ids:
                    item = insight_by_id.get(identifier)
                    if item:
                        allowed_text_parts.extend((item.title, item.narrative))
                allowed_numbers = self._numbers(" ".join(allowed_text_parts))
                claimed_numbers = self._numbers(" ".join((slide.title, slide.message, *slide.bullets)))
                unsupported_numbers = claimed_numbers - allowed_numbers
                if unsupported_numbers:
                    errors.append(f"slide {slide.id} contains unsupported numeric claims: {sorted(unsupported_numbers)}")

        summaries = [slide for slide in plan.slides if slide.slide_type == "executive_summary"]
        risks = [slide for slide in plan.slides if slide.slide_type == "risks"]
        if summaries and risks:
            summary_text = {
                self._normalized_text(value)
                for value in (summaries[0].message, *summaries[0].bullets)
                if value.strip()
            }
            risk_text = {
                self._normalized_text(value)
                for value in (risks[0].message, *risks[0].bullets)
                if value.strip()
            }
            if summary_text & risk_text:
                errors.append("the risks slide repeats executive-summary language")

        if errors:
            raise ValueError("Invalid presentation plan: " + "; ".join(errors))
        return plan

    @staticmethod
    def _numbers(value: str) -> set[str]:
        grouped_or_decimal = re.compile(
            r"(?<![A-Za-z0-9_])[+-]?(?:"
            r"\d{1,3}(?:[, '\u00a0\u202f\u2019]\d{3})+(?:\.\d+)?"
            r"|\d+(?:[.,]\d+)?"
            r")%?"
        )
        return {
            PresentationPlanValidator._normalize_number(match)
            for match in grouped_or_decimal.findall(value)
        }

    @staticmethod
    def _normalize_number(value: str) -> str:
        clean = value.replace("\u00a0", " ").replace("\u202f", " ").replace("\u2019", "'").lstrip("+")
        suffix = "%" if clean.endswith("%") else ""
        clean = clean.removesuffix("%")
        if re.fullmatch(r"-?\d{1,3}(?:[, ' ]\d{3})+(?:\.\d+)?", clean):
            clean = re.sub(r"[, ' ]", "", clean)
        elif clean.count(",") == 1 and "." not in clean:
            clean = clean.replace(",", ".")
        return clean + suffix

    @staticmethod
    def _normalized_text(value: str) -> str:
        return " ".join(re.sub(r"[^a-z0-9%]+", " ", value.casefold()).split())

    @classmethod
    def _allowed_company_numbers(
        cls,
        pages: set[int],
        result: PipelineResult,
    ) -> set[str]:
        text_parts: list[str] = []
        page_by_num = {page.page_number: page.text for page in result.document.pages}
        for p in pages:
            if p in page_by_num:
                text_parts.append(page_by_num[p])
        for obs in result.observations:
            obs_pages = {source.page for source in obs.evidence}
            if not pages or (obs_pages & pages):
                for val in (obs.value, obs.raw_value, obs.period, obs.entity):
                    if val is not None:
                        text_parts.append(str(val))
                if obs.dimensions:
                    text_parts.extend(str(v) for v in obs.dimensions.values())
        for insight in result.insights:
            insight_pages = {source.page for source in insight.evidence}
            if not pages or (insight_pages & pages):
                text_parts.append(insight.title)
                text_parts.append(insight.narrative)
        return cls._numbers(" ".join(text_parts))
