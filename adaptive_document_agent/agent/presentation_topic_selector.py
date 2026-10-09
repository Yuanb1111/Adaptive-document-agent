"""Select evidence-bound presentation questions before choosing any charts."""

import json

from adaptive_document_agent.models import PipelineResult, PresentationTopicSelection
from adaptive_document_agent.services.llm import LLMGateway
from adaptive_document_agent.services.presentation_evidence import (
    ambiguous_source_table_ids,
    evidence_groups,
    observation_uses_ambiguous_table,
)
from adaptive_document_agent.utils.ids import stable_id

from .prompting import load_prompt, untrusted_document_message


def _reconciles_order(order, index, waterfall_data, visual_block_type) -> bool:
    """Check only existence of a source-consistent arithmetic ordering."""
    try:
        waterfall_data(visual_block_type(role="waterfall", observation_ids=list(order)), index)
    except ValueError:
        return False
    return True


def series_directory(result: PipelineResult) -> tuple[list[dict[str, object]], dict[str, list]]:
    """Expose every extracted metric scope, without truncating to a chart quota."""
    directory: list[dict[str, object]] = []
    lookup: dict[str, list] = {}
    from adaptive_document_agent.services.presentation_ratio_definitions import ratio_definitions
    definitions = ratio_definitions(result)
    ambiguous_tables = ambiguous_source_table_ids(result)
    eligible = [
        item for item in result.observations
        if not observation_uses_ambiguous_table(item, ambiguous_tables)
    ]
    from adaptive_document_agent.services.source_scope_completeness import declared_scope_series
    groups = [*evidence_groups(eligible), *declared_scope_series(result, eligible)]
    for group in groups:
        if not any(item.value is not None and item.evidence for item in group):
            continue
        by_period: dict[str, set[float]] = {}
        for item in group:
            if item.period and item.value is not None:
                by_period.setdefault(item.period, set()).add(float(item.value))
        if any(len(values) > 1 for values in by_period.values()):
            # Missing category/series labels make these same-period values
            # impossible to interpret as a single coherent measure.
            continue
        identifier = stable_id("presentation_series", *(item.id for item in group))
        if identifier in lookup:
            continue
        lookup[identifier] = group
        first = group[0]
        pages = sorted({e.page for item in group for e in item.evidence})
        periods = list(dict.fromkeys(item.period for item in group if item.period))
        directory.append({
            "id": identifier,
            "metric": first.metric_original,
            "canonical_metric": first.metric_canonical if first.metric_canonical != first.metric_original else None,
            "periods": periods,
            "unit": first.unit,
            "raw_unit": first.raw_unit,
            "parent_section": first.parent_section,
            "currency": first.currency,
            "entity": first.entity,
            "dimensions": {
                key: value for key, value in {**first.dimensions, **first.category_dimensions}.items()
                if key not in {"table_context", "section", "column_role"}
            },
            "source_sections": sorted({item.source_section for item in group if item.source_section}),
            "source_pages": pages,
            "observation_count": len(group),
            "first_reported_value": group[0].raw_value,
            "last_reported_value": group[-1].raw_value,
            "evidence_status": "complete" if all(item.value is not None and item.evidence and item.validation_status == "valid" for item in group) else "qualified",
            "ratio_definitions": [
                {key: value for key, value in definition.items() if key != "observation_ids"}
                for definition in definitions
                if set(definition["observation_ids"]).intersection(item.id for item in group)
            ],
        })
    # A complete matrix is one selectable analytical view, so the model need
    # not spend all three series slots naming individual categories.
    from adaptive_document_agent.document_model import DocumentIndex
    from adaptive_document_agent.services.composition_candidates import presentation_compositions
    from adaptive_document_agent.services.composition_data import composition_data
    index = DocumentIndex(eligible)
    for chart in presentation_compositions(index):
        members = [index.get(oid) for oid in [*chart.observation_ids, *chart.total_observation_ids]]
        matrix = composition_data(chart, [index.get(oid) for oid in chart.observation_ids],
                                  [index.get(oid) for oid in chart.total_observation_ids])
        identifier = stable_id("presentation_composition", chart.id)
        lookup[identifier] = members
        directory.append({
            "id": identifier, "metric": chart.title, "canonical_metric": None,
            "periods": matrix.periods, "unit": members[0].unit, "currency": members[0].currency,
            "raw_unit": members[0].raw_unit, "parent_section": members[0].parent_section,
            "entity": members[0].entity,
            "dimensions": {"composition_categories": matrix.categories,
                           "source_tables": sorted({o.source_table for o in members if o.source_table}),
                           "reported_values": [{"metric": o.metric_original, "period": o.period,
                                                "raw_value": o.raw_value} for o in members]},
            "source_sections": sorted({o.source_section for o in members if o.source_section}),
            "source_pages": matrix.source_pages, "observation_count": len(members),
            "first_reported_value": None, "last_reported_value": None,
            "evidence_status": "complete", "ratio_definitions": [],
            "visual_kind": chart.chart_type,
        })
    source_pages = {page.page_number: page for page in result.document.pages}
    for item in directory:
        item.setdefault("visual_kind", "series")
        group = lookup[item["id"]]
        # Endpoints alone hide reversals and can conceal a recent comparison.
        item["reported_points"] = [
            [o.id, o.period, o.raw_value, o.value, o.unit_scale, o.period_basis,
             o.period_type, o.period_start, o.period_end, o.ifrs_status,
             o.audited_status, o.validation_status, sorted({e.page for e in o.evidence})]
            for o in group
        ]
        from adaptive_document_agent.services.source_row_qualifications import source_row_qualifications
        item['source_qualifications'] = source_row_qualifications(group, result.document, pages=source_pages)
    return directory, lookup


class PresentationTopicSelector:
    """Ask the configured model which questions the retained evidence warrants."""

    def __init__(self, gateway: LLMGateway) -> None:
        self.gateway = gateway

    def select(self, result: PipelineResult) -> PresentationTopicSelection:
        from adaptive_document_agent.services.company_discovery import CompanyProfileDiscovery

        directory, lookup = series_directory(result)
        if not directory:
            return PresentationTopicSelection()
        primary_pages = {
            page for start, end in result.profile.analysis_page_ranges
            for page in range(start, end + 1)
        }
        context_numbers = CompanyProfileDiscovery.rank_profile_pages(
            result.document, result.profile, max_pages=8
        )
        context_pages = [
            {"page": page.page_number, "text": page.text[:1600]}
            for page in result.document.pages
            if page.page_number in context_numbers
            and page.page_number not in primary_pages and page.text.strip()
        ]
        columns = (
            "id", "metric", "periods", "unit", "raw_unit", "parent_section", "currency", "entity", "dimensions",
            "source_sections", "source_pages", "observation_count",
            "first_reported_value", "last_reported_value", "evidence_status",
            "visual_kind",
            "reported_points",
        )
        payload = {
            "document_purpose": result.profile.document_purpose,
            "user_focus": result.profile.analysis_focus,
            "primary_analysis_ranges": result.profile.analysis_page_ranges,
            "important_sections": result.profile.important_sections,
            "series_columns": columns,
            "reported_point_columns": ["observation_id", "period", "raw_value", "value", "unit_scale",
                "period_basis", "period_type", "period_start", "period_end", "definition_basis",
                "audited_status", "validation_status", "source_pages"],
            "all_extracted_series": [[item[column] for column in columns] for item in directory],
            "ratio_definitions": [
                {"series_id": item["id"], "definitions": item["ratio_definitions"]}
                for item in directory if item["ratio_definitions"]
            ],
            'source_row_qualifications': [
                {'series_id': item['id'], 'notes': item['source_qualifications']}
                for item in directory if item['source_qualifications']
            ],
            "validated_insights": [
                {"id": item.id, "title": item.title, "narrative": item.narrative,
                 "importance": item.importance,
                 "source_pages": sorted({e.page for e in item.evidence})}
                for item in sorted(result.insights, key=lambda item: -item.importance)[:18]
                if item.evidence
            ],
            "background_page_excerpts": context_pages,
        }
        from .topic_coverage_review import source_period_views, review_topic_coverage
        payload["same_source_row_period_views"] = source_period_views(lookup)
        from .coverage_review_context import compact_context, encode
        # Reuse the complete-point encoding already used by coverage review.
        # No series or interior point is sampled away to shorten this request.
        messages = [
            {"role": "system", "content": load_prompt("presentation_topic_selection.txt")},
            untrusted_document_message(encode(compact_context(payload))),
        ]
        selection = self.gateway.generate_structured(
            messages,
            PresentationTopicSelection,
            stage="presentation",
        )
        from .topic_reference_binding import bind_topic_references
        bind_topic_references(selection, lookup, result)
        from adaptive_document_agent.services.presentation_ratio_definitions import prepare_topic_ratio_definitions
        prepare_topic_ratio_definitions(selection, lookup, result)
        from adaptive_document_agent.validation.topic_period_consistency import reconcile_topic_periods
        # The model owns the question; exact source-row rebinding follows its
        # explicit periods without another model request or changing raw facts.
        previous = result.presentation_topics
        result.presentation_topics = selection
        try:
            reconcile_topic_periods(result, lookup)
        finally:
            result.presentation_topics = previous
        from .topic_selection_repair import retain_valid_topics
        retained = retain_valid_topics(selection, lookup, primary_pages, result, self.gateway, self._validate)
        retained = review_topic_coverage(retained, result, lookup, primary_pages, payload,
                                         self.gateway, self._validate)
        prepare_topic_ratio_definitions(retained, lookup, result)
        return retained

    @staticmethod
    def _validate(
        selection: PresentationTopicSelection,
        lookup: dict[str, list],
        *, primary_pages: set[int] | None = None,
    ) -> None:
        from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator

        if lookup and not selection.topics:
            raise ValueError("No evidence-bound presentation topics were selected")
        topic_ids = [item.id for item in selection.topics]
        if len(topic_ids) != len(set(topic_ids)):
            raise ValueError("Presentation topic IDs must be unique")
        selected: set[str] = set()
        for topic in selection.topics:
            if not all((topic.id.strip(), topic.title.strip(), topic.question.strip(), topic.rationale.strip())):
                raise ValueError("Each presentation topic needs a title, question and selection reason")
            if not topic.series_ids or set(topic.series_ids) - lookup.keys():
                raise ValueError(f"Topic {topic.id} cites unknown or no metric series")
            if len(topic.series_ids) != len(set(topic.series_ids)):
                raise ValueError(f"Topic {topic.id} repeats a metric series")
            if len(topic.series_ids) > 3:
                from adaptive_document_agent.models import PresentationVisualBlock
                from adaptive_document_agent.services.presentation_matrix import topic_matrix_dimension

                members = list({item.id: item for sid in topic.series_ids for item in lookup[sid]}.values())
                if len(members) > 180:
                    raise ValueError(f"Topic {topic.id} exceeds the retained evidence capacity")
                if topic_matrix_dimension(members) is None:
                    from itertools import permutations
                    from adaptive_document_agent.services.presentation_waterfall import waterfall_data

                    index = {item.id: item for item in members}
                    if not (3 <= len(members) <= 6 and any(
                        _reconciles_order(order, index, waterfall_data, PresentationVisualBlock)
                        for order in permutations(index)
                    )):
                        from adaptive_document_agent.validation.presentation_parallel_series import validate_parallel_series
                        validate_parallel_series([lookup[sid] for sid in topic.series_ids])
            if primary_pages and any(
                not any(e.page in primary_pages for item in lookup[sid] for e in item.evidence)
                for sid in topic.series_ids
            ):
                raise ValueError(f"Topic {topic.id} uses a metric outside the primary analysis scope")
            allowed = set().union(*(PresentationPlanValidator._numbers(str(value))
                for sid in topic.series_ids for item in lookup[sid]
                for value in (item.raw_value, item.value, item.period)
                if value is not None
            ))
            claimed = PresentationPlanValidator._numbers(" ".join(
                (topic.title, topic.question, topic.rationale, topic.takeaway, *topic.caveats)
            ))
            if claimed - allowed:
                raise ValueError(f"Topic {topic.id} contains unsupported numeric claims: {sorted(claimed - allowed)}")
            from adaptive_document_agent.validation.topic_period_consistency import topic_period_errors
            period_errors = topic_period_errors(topic, lookup)
            if period_errors:
                raise ValueError(" ".join(period_errors))
            selected.update(topic.series_ids)
        for omission in selection.omissions:
            if omission.series_id not in lookup or omission.series_id in selected or not omission.reason.strip():
                raise ValueError("An omission must name an unselected known series and explain why")
