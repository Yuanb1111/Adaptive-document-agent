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
        if main_slide_count > 12:
            errors.append("the main presentation may contain at most 12 planned slides")

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

        for slide in plan.slides:
            unknown_observations = set(slide.observation_ids) - observation_by_id.keys()
            unknown_insights = set(slide.insight_ids) - insight_by_id.keys()
            unknown_charts = set(slide.chart_ids) - chart_by_id.keys()
            if unknown_observations:
                errors.append(f"slide {slide.id} references unknown observations: {sorted(unknown_observations)}")
            if unknown_insights:
                errors.append(f"slide {slide.id} references unknown insights: {sorted(unknown_insights)}")
            if unknown_charts:
                errors.append(f"slide {slide.id} references unknown charts: {sorted(unknown_charts)}")
            if set(slide.source_pages) - valid_pages:
                errors.append(f"slide {slide.id} contains source pages outside the document")
            if slide.slide_type in {"analysis", "risks"} and not (
                slide.chart_ids or slide.observation_ids or slide.insight_ids
            ):
                errors.append(f"slide {slide.id} has no retained evidence references")
            if slide.slide_type == "analysis" and not slide.message.strip():
                errors.append(f"analysis slide {slide.id} must state one message")

            referenced_pages: set[int] = set()
            referenced_observation_ids = set(slide.observation_ids)
            for identifier in slide.observation_ids:
                item = observation_by_id.get(identifier)
                if item:
                    referenced_pages.update(source.page for source in item.evidence)
            for identifier in slide.insight_ids:
                item = insight_by_id.get(identifier)
                if item:
                    referenced_pages.update(source.page for source in item.evidence)
            for identifier in slide.chart_ids:
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
                for identifier in slide.insight_ids:
                    item = insight_by_id.get(identifier)
                    if item:
                        allowed_text_parts.extend((item.title, item.narrative))
                allowed_numbers = self._numbers(" ".join(allowed_text_parts))
                claimed_numbers = self._numbers(" ".join((slide.title, slide.message, *slide.bullets)))
                unsupported_numbers = claimed_numbers - allowed_numbers
                if unsupported_numbers:
                    errors.append(f"slide {slide.id} contains unsupported numeric claims: {sorted(unsupported_numbers)}")

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
