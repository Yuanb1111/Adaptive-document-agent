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
from adaptive_document_agent.utils.series_directory_cache import SeriesDirectoryCache

from .prompting import load_prompt, untrusted_document_message, with_presentation_limits

_series_directory_cache = SeriesDirectoryCache()


def _reconciles_order(order, index, waterfall_data, visual_block_type) -> bool:
    """Check only existence of a source-consistent arithmetic ordering."""
    try:
        waterfall_data(visual_block_type(role="waterfall", observation_ids=list(order)), index)
    except ValueError:
        return False
    return True


def series_directory(result: PipelineResult) -> tuple[list[dict[str, object]], dict[str, list]]:
    """Expose every extracted metric scope, without truncating to a chart quota."""
    return _series_directory_cache.directory(result, _build_series_directory)


def _build_series_directory(result: PipelineResult) -> tuple[list[dict[str, object]], dict[str, list]]:
    """Build the full source-owned directory; cache hits never retain its objects."""
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
    from adaptive_document_agent.services.presentation_source_series import distinct_source_series
    groups = [source for group in groups for source in distinct_source_series(group)]
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
        from adaptive_document_agent.services.presentation_interval_evidence import latest_numeric_intervals
        item['latest_numeric_intervals'] = latest_numeric_intervals(group) if item['visual_kind'] == 'series' else []
        from adaptive_document_agent.services.source_row_qualifications import source_row_qualifications
        item['source_qualifications'] = source_row_qualifications(group, result.document, pages=source_pages)
    return directory, lookup


class PresentationTopicSelector:
    """Ask the configured model which questions the retained evidence warrants."""

    def __init__(self, gateway: LLMGateway) -> None:
        self.gateway = gateway

    def select(self, result: PipelineResult) -> PresentationTopicSelection:
        from adaptive_document_agent.services.company_discovery import CompanyProfileDiscovery
        from adaptive_document_agent.utils.timing import record_timing

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
            "latest_numeric_intervals",
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
            'latest_numeric_interval_columns': ['start_period', 'end_period', 'normalized_value_change'],
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
            {"role": "system", "content": with_presentation_limits(load_prompt("presentation_topic_selection.txt"))},
            untrusted_document_message(encode(compact_context(payload), factor_cells=True)),
        ]
        from .report_requirements import instruction_messages
        messages[1:1] = instruction_messages(result.profile, purpose='topic selection and narrative detail')
        from adaptive_document_agent.services.slide_budgets import resolved_limits, introduction_limit
        limits = resolved_limits(result.profile.report_requirements)
        if limits:
            introduction = introduction_limit(result.profile.report_requirements) or 0
            available = max(0, min(limits) - introduction - 5)
            if resolved_limits(result.profile.report_requirements, scope='all'):
                # Include Data Index, a complete conclusion and closing in the
                # same file budget; source appendices have no outside allowance.
                available = max(0,min(limits)-introduction-8)
            analysis_limits = resolved_limits(result.profile.report_requirements,section='analysis')
            if analysis_limits:
                available = min(available,min(analysis_limits))
            messages.insert(1, {'role': 'user', 'content':
                f'The report has at most {min(limits)} physical audience slides. Reserve up to '
                f'{introduction} introduction slides and five for cover, contents, executive brief, '
                f'source limitations and closing. At most {available} slides remain for analytical '
                'topics and their continuations. Choose a coherent set of the most valuable supported '
                'questions within this space; combine related questions rather than enumerating every '
                'series. State honest evidence-bound omission reasons. Full extracted evidence remains '
                'in diagnostics. Data Index source references count separately under a body budget; '
                'every analytical continuation still counts in the body, wherever it is placed. Never drop important caveats, '
                'change claims or add topics merely to fill this budget.'})
        with record_timing(result.stage_details_ms, 'topic_initial_selection'):
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
        with record_timing(result.stage_details_ms, 'topic_validation_repair'):
            retained = retain_valid_topics(selection, lookup, primary_pages, result, self.gateway, self._validate)
        from .topic_evidence_review import review_topic_evidence
        with record_timing(result.stage_details_ms, 'topic_source_review'):
            retained = review_topic_evidence(retained, lookup, result, self.gateway, self._validate,
                                             primary_pages=primary_pages)
        with record_timing(result.stage_details_ms, 'topic_coverage_review'):
            retained = review_topic_coverage(retained, result, lookup, primary_pages, payload,
                                             self.gateway, self._validate)
        from .topic_caveat_review import reconcile_caveats
        with record_timing(result.stage_details_ms, 'topic_caveat_review'):
            reconcile_caveats(retained, directory, result, self.gateway)
        prepare_topic_ratio_definitions(retained, lookup, result)
        with record_timing(result.stage_details_ms, 'topic_final_source_review'):
            reviewed = review_topic_evidence(retained, lookup, result, self.gateway, self._validate,
                                             primary_pages=primary_pages, allow_correction=False)
        if reviewed != retained:
            raise ValueError('Coverage synthesis introduced unsupported topic meaning; source coverage needs review.')
        return reviewed

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
                        try:
                            invalid_series = []
                            for sid in topic.series_ids:
                                try:
                                    validate_parallel_series([lookup[sid]])
                                except ValueError as invalid:
                                    invalid_series.append(f'series {sid}: {invalid}')
                            if invalid_series:
                                raise ValueError('; '.join(invalid_series))
                        except ValueError as exc:
                            raise ValueError(f'Topic {topic.id} has incompatible parallel evidence: {exc}') from exc
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
            # Standalone source cells use accounting parentheses without a
            # currency prefix. The prose tokenizer recognises RMB(123), but
            # cannot infer that a bare parenthesised number is accounting data.
            # Parse the complete raw cell with the numeric engine and retain
            # its sign; no scaling or missing unit is inferred here.
            from adaptive_document_agent.extraction.numeric_parser import parse_number
            for sid in topic.series_ids:
                for item in lookup[sid]:
                    parsed = parse_number(item.raw_value)
                    if parsed is not None:
                        allowed.update(PresentationPlanValidator._numbers(str(parsed.value)))
                    if item.unit == 'percent' or item.unit_family == 'percentage':
                        allowed.update(PresentationPlanValidator._numbers(f'{item.value}%'))
                        if parsed is not None:
                            allowed.update(PresentationPlanValidator._numbers(f'{parsed.value}%'))
            from adaptive_document_agent.validation.source_label_numbers import without_source_label_annotations
            from adaptive_document_agent.validation.topic_source_notation import without_topic_source_notation
            members = [item for sid in topic.series_ids for item in lookup[sid]]
            def numeric_claims(text):
                return PresentationPlanValidator._numbers(without_topic_source_notation(
                    without_source_label_annotations(text, members), members))
            claimed = numeric_claims(" ".join(
                (topic.title, topic.question, topic.rationale, topic.takeaway, *topic.caveats)
            ))
            if claimed - allowed:
                fields = {'title': topic.title, 'question': topic.question,
                          'rationale': topic.rationale, 'takeaway': topic.takeaway,
                          **{f'caveats[{i}]': text for i, text in enumerate(topic.caveats)}}
                rejected = {name: text for name, text in fields.items()
                            if numeric_claims(text) - allowed}
                periods = sorted({item.period for sid in topic.series_ids for item in lookup[sid] if item.period})
                raise ValueError(f"Topic {topic.id} contains unsupported numeric claims: {sorted(claimed - allowed)}; "
                                 f"rejected fields: {json.dumps(rejected, ensure_ascii=False)}; "
                                 f"selected source periods: {periods}. Correct every rejected field, including caveats; "
                                 "remove unsupported dates/values entirely from this topic. Negating them as "
                                 "'not covered' or 'unavailable' still repeats the unsupported token. "
                                 "Use a general scope qualification without that date/value, or cite only the listed source periods.")
            from adaptive_document_agent.validation.topic_period_consistency import topic_period_errors
            period_errors = topic_period_errors(topic, lookup)
            if period_errors:
                raise ValueError(" ".join(period_errors))
            selected.update(topic.series_ids)
        for omission in selection.omissions:
            if omission.series_id not in lookup or omission.series_id in selected or not omission.reason.strip():
                raise ValueError("An omission must name an unselected known series and explain why")
