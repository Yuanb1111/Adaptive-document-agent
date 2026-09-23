"""Markdown report rendering with facts, calculations, coverage, and citations."""

from collections import defaultdict

from adaptive_document_agent.document_model import display_metric_name, is_meaningful_metric, metric_key, period_sort_key
from adaptive_document_agent.models import ChartPlan, DocumentProfile, Insight, Observation, ReportPlan, ValidationIssue
from adaptive_document_agent.validation.coverage_validator import assess_coverage


class ReportGenerator:
    def generate(
        self,
        profile: DocumentProfile,
        plan: ReportPlan,
        insights: list[Insight],
        warnings: list[ValidationIssue],
        *,
        observations: list[Observation] | None = None,
        charts: list[ChartPlan] | None = None,
    ) -> str:
        by_id = {insight.id: insight for insight in insights}
        lines = [f"# {plan.title}", "", f"**Document purpose:** {profile.document_purpose}", ""]
        if profile.document_summary.strip():
            pages = ", ".join(map(str, sorted(set(profile.document_summary_pages))))
            source = f" (Sources: pages {pages})" if pages else ""
            lines.extend([f"## {profile.overview_title.strip() or 'Document overview'}", "", profile.document_summary.strip() + source, ""])
        lines.extend(self._coverage(profile, observations or [], charts or []))
        lines.extend(self._topic_coverage(profile, observations or []))
        lines.extend(self._reported_facts(profile, observations or []))
        for section in plan.sections:
            lines.extend([f"## {section.title}", ""])
            if section.title == "Data Quality and Limitations":
                for note in profile.data_quality_notes:
                    lines.append(f"- {note}")
                for warning in self._display_warnings(warnings):
                    lines.append(f"- [{warning.severity.upper()}] {warning.message}")
                lines.append("")
                continue
            for identifier in section.insight_ids:
                insight = by_id.get(identifier)
                if not insight:
                    continue
                label = insight.kind.replace("_", " ").title()
                pages = sorted({source.page for source in insight.evidence})
                source = f" (Sources: pages {', '.join(map(str, pages))})" if pages else ""
                lines.extend([f"### {insight.title}", "", f"**{label}.** {insight.narrative}{source}", ""])
        if warnings and not any(section.title == "Data Quality and Limitations" for section in plan.sections):
            lines.extend(["## Validation Warnings", ""])
            lines.extend(f"- [{warning.severity.upper()}] {warning.message}" for warning in self._display_warnings(warnings))
            lines.append("")
        return "\n".join(lines).strip() + "\n"

    @staticmethod
    def _coverage(profile: DocumentProfile, observations: list[Observation], charts: list[ChartPlan]) -> list[str]:
        displayable = [item for item in observations if is_meaningful_metric(item)]
        if not displayable:
            return []
        metrics = {metric_key(item) for item in displayable}
        tables = {source.table_id for item in displayable for source in item.evidence if source.table_id}
        evidence_pages = {source.page for item in displayable for source in item.evidence}
        displayable_ids = {item.id for item in displayable}
        chart_count = sum(any(identifier in displayable_ids for identifier in chart.observation_ids) for chart in charts)
        ranges = ", ".join(f"{start}-{end}" for start, end in profile.analysis_page_ranges) or "complete document"
        return [
            "## Evidence Coverage",
            "",
            f"- Analysis scope: pages {ranges}.",
            f"- Retained fact base: {len(displayable)} observations across {len(metrics)} metrics and {len(tables)} source tables.",
            f"- Page-level evidence is retained from {len(evidence_pages)} pages; {chart_count} validated visualisations were planned.",
            "- The selected facts below are a readable overview; the complete retained fact base remains available in the CSV export.",
            "",
        ]

    def _reported_facts(
        self,
        profile: DocumentProfile,
        observations: list[Observation],
        *,
        maximum_metrics: int = 15,
        maximum_rows_per_metric: int = 6,
    ) -> list[str]:
        eligible = [
            item for item in observations
            if item.value is not None and item.evidence and item.confidence >= 0.5 and is_meaningful_metric(item)
        ]
        if not eligible:
            return []
        groups: dict[str, list[Observation]] = defaultdict(list)
        for item in eligible:
            key = metric_key(item)
            if key not in {"page", "pages"}:
                groups[key].append(item)
        purpose = " ".join([profile.document_purpose, *profile.metrics]).casefold()

        def score(group: tuple[str, list[Observation]]) -> tuple[int, int, float, int, str]:
            name, items = group
            relevance = int(name in purpose or any(term.casefold() in name for term in profile.metrics if term.strip()))
            periods = len({item.period for item in items if item.period})
            confidence = sum(item.confidence for item in items) / len(items)
            return relevance, periods, confidence, min(len(items), 20), name

        selected = sorted(groups.items(), key=score, reverse=True)[:maximum_metrics]
        rows: list[str] = []
        for _, items in selected:
            unique: dict[tuple[object, ...], Observation] = {}
            for item in sorted(items, key=lambda value: period_sort_key(value.period)):
                key = item.period, item.entity, tuple(sorted(item.dimensions.items())), item.raw_value
                unique.setdefault(key, item)
            for item in list(unique.values())[:maximum_rows_per_metric]:
                context = item.period or item.entity or ", ".join(f"{key}={value}" for key, value in item.dimensions.items()) or "—"
                units = self._source_unit_label(item)
                pages = ", ".join(map(str, sorted({source.page for source in item.evidence})))
                rows.append(
                    "| " + " | ".join(
                        self._escape(value)
                        for value in (display_metric_name(item), context, item.raw_value, units, pages, f"{item.confidence:.2f}")
                    ) + " |"
                )
        if not rows:
            return []
        return [
            "## Reported Data Overview",
            "",
            "**Reported Facts.** These values are reproduced from retained source observations; they are not model-generated calculations.",
            "",
            "| Original metric | Period / context | Reported value | Unit / currency | Source page | Confidence |",
            "|---|---|---:|---|---:|---:|",
            *rows,
            "",
        ]

    @staticmethod
    def _topic_coverage(profile: DocumentProfile, observations: list[Observation], *, maximum: int = 20) -> list[str]:
        assessed = assess_coverage(profile, observations)
        if not assessed:
            return []
        rows: list[str] = []
        for item in assessed[:maximum]:
            metrics = ", ".join(item.matched_metrics[:4]) or "—"
            periods = ", ".join(item.periods[:8]) or "—"
            pages = ", ".join(map(str, item.pages[:12])) or "—"
            rows.append(
                "| " + " | ".join(
                    ReportGenerator._escape(value)
                    for value in (item.topic, item.status, metrics, item.observation_count, periods, pages)
                ) + " |"
            )
        focus = " ".join((profile.analysis_focus or "").split())
        focus_line = f" User focus: {focus[:500]}" if focus else ""
        return [
            "## Analysis Coverage Check",
            "",
            "Coverage targets are derived from semantic document discovery aligned with the user's requested focus; missing topics are reported rather than inferred." + focus_line,
            "",
            "| Priority topic | Status | Matched retained metrics | Supported observations | Periods | Source pages |",
            "|---|---|---|---:|---|---|",
            *rows,
            "",
        ]

    @staticmethod
    def _escape(value: object) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ")

    @staticmethod
    def _source_unit_label(item: Observation) -> str:
        parts = [item.raw_unit, item.currency, item.unit]
        if item.unit_scale and item.unit_scale != 1:
            parts.append(f"source scale ×{item.unit_scale:,.0f}")
        return " / ".join(dict.fromkeys(value for value in parts if value)) or "—"

    @staticmethod
    def _display_warnings(warnings: list[ValidationIssue], *, maximum_per_code: int = 8) -> list[ValidationIssue]:
        output: list[ValidationIssue] = []
        counts: dict[str, int] = {}
        omitted: dict[str, int] = {}
        for warning in warnings:
            count = counts.get(warning.code, 0)
            if count < maximum_per_code:
                output.append(warning)
            else:
                omitted[warning.code] = omitted.get(warning.code, 0) + 1
            counts[warning.code] = count + 1
        for code, count in omitted.items():
            output.append(ValidationIssue(code=code, message=f"{count} additional '{code}' issue(s) are retained in the technical result data.", stage="report", severity="info"))
        return output
