"""One bounded semantic review of evidence left outside the presentation story.

Structural coverage is a retrieval signal, not an importance score. The model
decides whether a missing series changes the interpretation or is redundant.
"""

from __future__ import annotations

import json
from typing import Callable, Literal

from pydantic import BaseModel, Field, ValidationError

from adaptive_document_agent.models import Observation, PipelineResult, PresentationTopicSelection, ValidationIssue
from adaptive_document_agent.models.presentation import PresentationOmission
from adaptive_document_agent.services.llm import LLMGateway
from adaptive_document_agent.services.llm.exceptions import LLMResponseError, LLMTransportError
from .prompting import load_prompt, untrusted_document_message, with_presentation_limits
from .coverage_representation import representation_links

MAX_REVIEW_CHARACTERS = 120_000
MAX_REVIEW_BATCHES = 24
MAX_REVIEW_CALLS = MAX_REVIEW_BATCHES + 12
MAX_REVIEW_OUTPUT_TOKENS = 8192
MAX_REVIEW_DECISIONS = 32
# Delta output contains no repeated topic descriptions, so twice as many
# complete per-series decisions fit the same bounded output contract.
MAX_DELTA_DECISIONS = 64


def _missing_included_facts(reviewed, lookup):
    """Explain the exact failed bindings; do not infer semantic equivalence."""
    selected = [o for topic in reviewed.topics for sid in topic.series_ids for o in lookup.get(sid, [])]
    missing = {}
    fields = ('id', 'metric_original', 'parent_section', 'period', 'period_basis', 'period_type', 'period_start', 'period_end',
              'as_of_date', 'raw_value', 'value', 'unit', 'raw_unit', 'unit_scale', 'currency',
              'entity', 'audited_status', 'ifrs_status', 'fact_type', 'dimensions', 'category_dimensions',
              'validation_status', 'anomaly_notes')
    for decision in reviewed.coverage_decisions:
        if decision.decision != 'include':
            continue
        facts = [{**{key: getattr(o, key) for key in fields},
                  'source_pages': sorted({e.page for e in o.evidence}),
                  'source_row_labels': sorted({e.row_label for e in o.evidence if e.row_label})}
                 for o in lookup.get(decision.series_id, [])
                 if representation_links([o], selected) is None]
        if facts:
            missing[decision.series_id] = facts
    return missing


def _validate_batch(reviewed, current, requested, lookup, primary_pages, validate):
    from .topic_reference_binding import bind_topic_references
    bind_topic_references(reviewed, lookup)
    revised = PresentationTopicSelection(topics=reviewed.topics, omissions=reviewed.omissions)
    validate(revised, lookup, primary_pages=primary_pages)
    previous_ids = {sid for topic in current.topics for sid in topic.series_ids}
    final_ids = {sid for topic in revised.topics for sid in topic.series_ids}
    deferred = final_ids - previous_ids - set(requested)
    if deferred:
        raise ValueError('Batch review selected deferred evidence without its complete context: '
                         + ', '.join(sorted(deferred)) + '. Use only selectable_series_ids; '
                         'these deferred series require a later batch, not an include decision here.')
    previous = {o.id for sid in previous_ids for o in lookup[sid]}
    selected = [o for sid in final_ids for o in lookup[sid]]
    if not previous <= {o.id for o in selected}:
        raise ValueError('Batch review removed accepted source evidence.')
    local = {d.series_id: d for d in reviewed.coverage_decisions}
    if len(local) != len(reviewed.coverage_decisions) or set(local) != set(requested):
        raise ValueError('Coverage review must decide each requested series exactly once. Missing: '
                         + ', '.join(sorted(set(requested) - set(local))))
    links = {sid: representation_links(lookup[sid], selected) for sid in requested}
    mismatches = [sid for sid, d in local.items() if not d.reason.strip()
                  or (d.decision == 'include' and links[sid] is None)]
    if mismatches:
        raise ValueError('Coverage decision must match the evidence actually selected: ' + ', '.join(mismatches))
    for sid, decision in list(local.items()):
        if decision.decision == 'omit' and links[sid] is not None:
            # A model may call a duplicate view "omitted" because it need not
            # occupy another topic. Every exact source fact is nevertheless
            # already selected. Reconcile coverage bookkeeping, not importance
            # or topic choice; the untouched model decision stays in the audit.
            local[sid] = CoverageDecision(series_id=sid, decision='include',
                reason='All source facts are represented by model-selected evidence; '
                       'the original omission reasoning remains in the batch audit.')
    revised.omissions = [o for o in revised.omissions if links.get(o.series_id) is None]
    return revised, local, {sid: link for sid, link in links.items() if link is not None}


def _review_batch(context, current, requested, lookup, primary_pages, gateway, validate, audit, budget=None,
                  instructions=()):
    """Bound targeted repairs; stop repeated errors and retain every attempt."""
    from .coverage_review_context import encode
    budget = budget if budget is not None else {'calls': 0}
    encoded = encode(context)
    messages = [
        {'role': 'system', 'content': with_presentation_limits(load_prompt('presentation_topic_selection.txt')) + '\n\n'
         + load_prompt('presentation_topic_coverage_review.txt') + '\n'
         'Retain every current selected source observation. Choose only fully evidenced series in this request. '
         'Deferred catalog entries have no decision yet. Read point_encoding; constants apply to every point. '
         'Read catalog_encoding and period_view_encoding when present; dictionary cells are exact source metadata. '
         'An include decision needs all facts actually represented, with matching values, periods, units, '
         'definitions, categories and audit status; matching page numbers or measure names is insufficient.'},
        *instructions,
        untrusted_document_message(encoded),
    ]
    topic_limit = PresentationTopicSelection.model_json_schema()['properties']['topics']['maxItems']
    if len(current.topics) >= topic_limit - 1:
        messages[0]['content'] += (
            f' The accepted selection has {len(current.topics)} topics; the complete response has a hard limit '
            f'of {topic_limit} topics, leaving {topic_limit - len(current.topics)} additional slots. '
            'Regroup complementary evidence under a supported shared question when needed. '
            'Do not return one topic for every requested series or drop accepted observations to meet the limit.')
    rejected_errors = set()
    initial_messages = list(messages)
    for attempt in range(3):
        if budget['calls'] >= MAX_REVIEW_CALLS:
            raise ValueError('Coverage model-call budget exhausted; remaining evidence requires review.')
        budget['calls'] += 1
        try:
            reviewed = gateway.generate_structured(messages, TopicCoverageReview,
                                                   stage='presentation', allow_repair=False,max_tokens=MAX_REVIEW_OUTPUT_TOKENS)
        except LLMResponseError as exc:
            # A topic-count overflow needs a semantic regrouping with source
            # context, not truncation or an evidence-blind format-only repair.
            cause = exc.__cause__
            response = getattr(exc, 'response', None)
            if not isinstance(cause, ValidationError) or response is None:
                raise
            errors = cause.errors(include_input=False, include_url=False)
            error = json.dumps(errors, default=str, sort_keys=True)
            audit.setdefault('attempts', []).append({'invalid_response': response.text, 'validation_error': error})
            if attempt == 2 or error in rejected_errors:
                raise
            rejected_errors.add(error)
            feedback = {'schema_errors': errors, 'rejected_output': response.text}
            if len(encoded) + len(encode(feedback)) > MAX_REVIEW_CHARACTERS:
                raise ValueError('Schema correction context exceeds the bounded review budget.') from exc
            messages = initial_messages + [untrusted_document_message(encode(feedback)),
                {'role': 'user', 'content': f'Correct the listed schema paths. Return at most {topic_limit} topics '
                 'and all requested coverage decisions. Preserve every accepted source observation. '
                 'For topic-count overflow, regroup evidence only when it answers a shared question; '
                 'do not truncate topics or remove accepted evidence. The original full source context remains above.'}]
            continue
        entry = {'review': reviewed.model_dump(mode='json')}
        audit.setdefault('attempts', []).append(entry)
        audit['review'] = entry['review']
        try:
            revised, decisions, links = _validate_batch(reviewed, current, requested,
                                                       lookup, primary_pages, validate)
            audit['representation_links'] = links
            return revised, decisions
        except ValueError as exc:
            entry['validation_error'] = str(exc)
            if attempt == 2 or str(exc) in rejected_errors:
                raise
            rejected_errors.add(str(exc))
            missing_facts = _missing_included_facts(reviewed, lookup)
            feedback = {'validation_error': str(exc),
                        'included_but_unrepresented_facts': missing_facts,
                        'unbound_include_series_ids': list(missing_facts),
                        'rejected_topics': [t.model_dump(mode='json') for t in reviewed.topics]}
            if len(encoded) + len(encode(feedback)) > MAX_REVIEW_CHARACTERS:
                feedback.pop('rejected_topics')
            if len(encoded) + len(encode(feedback)) > MAX_REVIEW_CHARACTERS:
                raise ValueError('Repair context exceeds the bounded review budget.') from exc
            messages = initial_messages + [untrusted_document_message(encode(feedback)),
                {'role': 'user', 'content': 'Repair this rejected review using the original full evidence context. '
                 'Return the complete topics and exactly one decision for each requested series. '
                 'If a material series is absent, select it; do not label it included without its facts. '
                 'Read included_but_unrepresented_facts: these exact raw values, periods, units and '
                 'source rows are absent from your selected evidence. Similar measure names and '
                 'a single matching period do not cover different rows or other periods. '
                 'For each unbound_include_series_id, either add that exact series ID to a '
                 'suitable topic.series_ids, or change its decision to omit with your explicit '
                 'reason. Do not repeat include while pointing to a different series with equal '
                 'numbers: its source row, parent section, definition or status failed exact binding. '
                 'An analytical redundancy judgment is an omit reason, not proof of exact inclusion. '
                 'A caveat cannot supply a missing period, citation or valid value. If a selected '
                 'series is structurally ineligible, remove it from the topic and give an explicit '
                 'evidence-limitation omission decision; do not invent its missing metadata or '
                 'repeat the same invalid series under another topic title. '
                 'Explicitly explain omissions. Preserve all previously accepted observations.'}]


class CoverageDecision(BaseModel):
    series_id: str
    decision: Literal["include", "omit"]
    reason: str = Field(min_length=1, max_length=400)


class TopicCoverageReview(PresentationTopicSelection):
    coverage_decisions: list[CoverageDecision] = Field(default_factory=list)


def coverage_review_pending(result: PipelineResult) -> bool:
    """A historical failed review clears only after successful or full coverage."""
    latest = next((issue for issue in reversed(result.validation_warnings)
        if issue.code in {"presentation_topic_coverage_review", "presentation_topic_coverage_unresolved"}), None)
    if latest is None:
        return False
    from .presentation_topic_selector import series_directory
    _, lookup = series_directory(result)
    if latest.code == 'presentation_topic_coverage_review':
        audit = json.loads(latest.message)
        if 'source_fingerprint' not in audit:
            return False  # Preserve legacy checkpoint semantics.
        from .coverage_review_binding import completed_review_is_current
        return not completed_review_is_current(result, audit, lookup)
    selected = {sid for topic in (result.presentation_topics.topics if result.presentation_topics else [])
                for sid in topic.series_ids}
    represented = [item for sid in selected if sid in lookup for item in lookup[sid]]
    return any(sid not in lookup or representation_links(lookup[sid], represented) is None
               for sid in latest.related_ids)


def source_period_views(lookup: dict[str, list[Observation]]) -> list[dict]:
    """Link exact source rows across bases without declaring them comparable."""
    from collections import defaultdict
    from adaptive_document_agent.validation.topic_period_consistency import _source_row
    from adaptive_document_agent.services.presentation_period_scope import _period

    rows = defaultdict(list)
    for sid, group in lookup.items():
        key = _source_row(group)
        if key is not None:
            rows[key].append(sid)
    views = []
    for ids in rows.values():
        if len(ids) < 2:
            continue
        entries = []
        for sid in ids:
            periods = {_period(item) for item in lookup[sid]}
            comparable = None not in periods and len(periods) > 1 and len({p[0] for p in periods}) == 1
            entries.append({"series_id": sid,
                "periods": list(dict.fromkeys(item.period for item in lookup[sid])),
                "internally_comparable_periods": comparable})
        views.append({"same_source_row": entries,
            "scope_note": "Separate period views. Never compare different durations or infer missing dates."})
    return views


def review_topic_coverage(
    selection: PresentationTopicSelection,
    result: PipelineResult,
    lookup: dict[str, list[Observation]],
    primary_pages: set[int],
    payload: dict,
    gateway: LLMGateway,
    validate: Callable[..., None],
) -> PresentationTopicSelection:
    """Retain the valid draft if coverage review fails; never select by Python rank."""
    selected_ids = {sid for topic in selection.topics for sid in topic.series_ids}
    represented = [item for sid in selected_ids for item in lookup[sid]]
    candidates = [sid for sid, group in lookup.items()
        if representation_links(group, represented) is None
        and (not primary_pages or any(e.page in primary_pages for item in group for e in item.evidence))]
    if not candidates:
        return selection

    review_payload = {**payload, "current_selection": selection.model_dump(mode="json"),
        "series_requiring_coverage_decision": candidates,
        "review_scope": "All available series with evidence not represented in the current selected topics."}
    encoded = json.dumps(review_payload, ensure_ascii=False, separators=(",", ":"))
    audit = {"original_selection": selection.model_dump(mode="json"), "candidate_series_ids": candidates}
    from .report_requirements import instruction_messages
    instructions = instruction_messages(result.profile, purpose='presentation coverage review')
    if instructions:
        instructions.append({'role': 'user', 'content':
            'Review every supplied evidence series, while preserving the requested audience page limits. '
            'A coverage decision is not a requirement for an additional slide. Combine complementary '
            'evidence under coherent questions, or give a specific source-supported omission reason. '
            'Do not expand the story into an exhaustive series catalogue or discard material caveats.'})

    def record(code, severity, details):
        from .coverage_review_binding import source_fingerprint
        result.validation_warnings.append(ValidationIssue(code=code, severity=severity,
            stage="presentation", related_ids=candidates,
            message=json.dumps({**audit, **details, 'source_fingerprint': source_fingerprint(lookup)}, ensure_ascii=False)))

    if len(encoded) > MAX_REVIEW_CHARACTERS or len(candidates) > MAX_REVIEW_DECISIONS:
        return _review_bounded(selection, candidates, lookup, primary_pages,
                               review_payload, gateway, validate, record, instructions=instructions)
    reviewed = None
    try:
        reviewed = gateway.generate_structured([
            {"role": "system", "content": with_presentation_limits(load_prompt("presentation_topic_selection.txt")) + "\n\n"
             + load_prompt("presentation_topic_coverage_review.txt")},
            *instructions,
            untrusted_document_message(encoded),
        ], TopicCoverageReview, stage="presentation", allow_repair=False,max_tokens=MAX_REVIEW_OUTPUT_TOKENS)
        from .topic_reference_binding import bind_topic_references
        bind_topic_references(reviewed, lookup, result)
        revised = PresentationTopicSelection(topics=reviewed.topics, omissions=reviewed.omissions)
        validate(revised, lookup, primary_pages=primary_pages)
        decisions = {item.series_id: item for item in reviewed.coverage_decisions}
        if len(decisions) != len(reviewed.coverage_decisions) or set(decisions) != set(candidates):
            raise ValueError("Coverage review must decide each requested series exactly once.")
        final_ids = {sid for topic in revised.topics for sid in topic.series_ids}
        final_observations = {item.id for sid in final_ids for item in lookup[sid]}
        for sid, decision in decisions.items():
            included = representation_links(lookup[sid], [o for selected_sid in final_ids for o in lookup[selected_sid]]) is not None
            if not decision.reason.strip() or (decision.decision == "include" and not included):
                raise ValueError("Coverage decision must match the evidence actually selected.")
            if decision.decision == 'omit' and included:
                decisions[sid] = CoverageDecision(series_id=sid, decision='include',
                    reason='All source facts are represented by model-selected evidence; '
                           'the original omission reasoning remains in the review audit.')
        # A completeness review may regroup topics, but must not silently erase
        # already accepted evidence to make room for a newly selected question.
        removed = selected_ids - final_ids
        explicitly_omitted = {item.series_id for item in revised.omissions}
        if any(not {item.id for item in lookup[sid]} <= final_observations
               and sid not in explicitly_omitted for sid in removed):
            raise ValueError("Previously selected evidence was removed without an explicit omission reason.")
    except (LLMResponseError, LLMTransportError, ValueError) as exc:
        record("presentation_topic_coverage_unresolved", "warning", {
            "reason": str(exc), "rejected_review": reviewed.model_dump(mode="json") if reviewed else None})
        return selection
    # Promote explicit model-authored exclusion reasons to the existing plan
    # coverage notes; the complete decisions remain in the durable audit.
    revised.omissions = [o for o in revised.omissions
                         if o.series_id not in decisions or decisions[o.series_id].decision == 'omit']
    omitted = {item.series_id for item in revised.omissions}
    for decision in decisions.values():
        if len(revised.omissions) >= 12:
            break
        if decision.decision == "omit" and decision.series_id not in omitted:
            revised.omissions.append(PresentationOmission(series_id=decision.series_id, reason=decision.reason))
            omitted.add(decision.series_id)
    record("presentation_topic_coverage_review", "info", {"review": reviewed.model_dump(mode="json"),
        "reconciled_coverage_decisions": [d.model_dump(mode='json') for d in decisions.values()]})
    return revised


def _review_bounded(selection, candidates, lookup, primary_pages, payload, gateway, validate, record,
                    *, instructions=()):
    """Review independent complete-fact deltas, then commit one validated merge."""
    from .coverage_delta_review import review_deltas
    return review_deltas(selection, candidates, lookup, primary_pages, payload, gateway,
        validate, record, instructions=instructions, characters=MAX_REVIEW_CHARACTERS,
        decision_limit=MAX_DELTA_DECISIONS, batch_limit=MAX_REVIEW_BATCHES,
        call_limit=MAX_REVIEW_CALLS, tokens=MAX_REVIEW_OUTPUT_TOKENS)
