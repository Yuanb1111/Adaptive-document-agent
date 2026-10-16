"""Bind independent semantic verdicts to the current draft, never a stale baseline."""
from concurrent.futures import CancelledError
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from adaptive_document_agent.services.introduction_audience import selection_digest
from adaptive_document_agent.services.llm.exceptions import LLMError
from adaptive_document_agent.services.source_quotes import normalize_quote
from .prompting import untrusted_document_message


class IntroductionReviewFinding(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['meaning', 'included_part', 'omitted_part']
    issue_type: Literal['unsupported_assertion', 'missing_qualification', 'new_assertion',
                        'atomicity', 'unspecified'] = 'unspecified'
    part_id: str
    meaning_id: str = ''
    current_meaning: str = ''
    source_quote: str = Field(min_length=1, max_length=16000)
    reason: str = Field(min_length=1, max_length=2000)


class IntroductionAudienceReview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    accepted: bool
    reason: str = Field(min_length=1, max_length=2000)
    repair_scope: Literal['selection', 'meanings'] = 'selection'
    # Defaults retain malformed/legacy verdicts in the audit. They never approve a draft.
    selection_digest: str = ''
    findings: list[IntroductionReviewFinding] = Field(default_factory=list)


def current_meanings(decisions):
    return [dict(meaning_id=f"{decision['part_id']}:meaning-{index + 1}",
                 part_id=decision['part_id'], meaning_index=index,
                 meaning=value['meaning'], source_quote=value['source_quote'])
            for decision in decisions for index, value in enumerate(decision['required_meanings'])]


def binding_errors(verdict, payload):
    """Validate identifiers/evidence only; a fresh model must decide semantic acceptance."""
    errors = []
    if verdict.selection_digest != payload['current_selection_digest']:
        errors.append('Review selection_digest does not identify the exact current draft')
    if verdict.accepted and verdict.findings:
        errors.append('An accepted review cannot contain unresolved findings')
    if not verdict.accepted and not verdict.findings:
        errors.append('A rejected review must identify its current source-bound findings')
    parts = {p['id']: p for p in payload['source']['parts']}
    decisions = {d['part_id']: d for d in payload['decisions']}
    meanings = {m['meaning_id']: m for m in payload['current_meanings']}
    for finding in verdict.findings:
        part = parts.get(finding.part_id)
        decision = decisions.get(finding.part_id)
        quote = normalize_quote(finding.source_quote)
        if part is None or decision is None:
            errors.append('Finding references an unknown source part: ' + finding.part_id)
            continue
        if not quote or quote not in normalize_quote(part['source_text']):
            errors.append('Finding lacks a literal quote from its own source part: ' + finding.part_id)
        if finding.kind == 'meaning':
            current = meanings.get(finding.meaning_id)
            if (current is None or current['part_id'] != finding.part_id
                    or current['meaning'] != finding.current_meaning):
                errors.append('Finding does not quote the exact current meaning: ' + finding.meaning_id)
            if finding.issue_type == 'new_assertion':
                errors.append('A new independent assertion needs a part-level finding after checking its whole meaning union')
        else:
            if finding.meaning_id or finding.current_meaning:
                errors.append('Part-level finding must not refer to an existing or stale meaning')
            if decision['include'] != (finding.kind == 'included_part'):
                errors.append('Finding does not match the current include/omit decision: ' + finding.part_id)
            if finding.kind == 'omitted_part' and verdict.repair_scope != 'selection':
                errors.append('An omitted-part finding requires selection repair scope')
    return errors


_BINDING_RULES = (
    ' The ONLY current candidate is decisions, indexed verbatim by current_meanings. '
    'Copy current_selection_digest into selection_digest. meaning_revision_base and '
    'inventory_revision_base are preservation-only historical baselines, NOT current copy. '
    'Never criticize a baseline assertion as though it were still present in the current draft. '
    'When rejecting, enumerate every detected current defect in findings. For a defect in an '
    'existing assertion, use kind=meaning, the exact current meaning_id, owning part_id and '
    'verbatim current_meaning text from current_meanings. For a missing assertion within an '
    'included part use kind=included_part; for an unjustifiably omitted source part use '
    'kind=omitted_part. Part findings leave meaning_id/current_meaning empty and identify '
    'the missing assertion in reason; do not use them to criticize existing wording without '
    'its exact meaning reference. Every finding must quote a nonempty literal source_quote '
    'from its own source part. A meaningful original assertion lost during revision is a '
    'missing assertion in the CURRENT included part, not a criticism of stale wording. '
    'Use repair_scope=selection for unjustified omitted parts. Accept only after the full '
    'semantic review, with findings empty. Do not invent findings merely to match an earlier '
    'verdict. If a prior verdict was unbound, independently review the full current draft '
    'again and return your actual current judgment; this is not automatic approval.'
    ' Review each included part as the UNION of all its current meanings, not each meaning as a '
    'standalone summary of its full source passage. Search every current meaning owned by that '
    'part before claiming an assertion is missing. Another current meaning may already express '
    'it completely. Classify every finding with issue_type: unsupported_assertion, '
    'missing_qualification, new_assertion or atomicity. A necessary qualification belongs to an '
    'already selected assertion; another independent source claim is new_assertion and needs a '
    'part-level finding with a section-materiality reason. An included source part does not '
    'require every fact in that passage to become selected copy. Do not turn optional numerical '
    'analyses, illustrative details or unrelated claims into qualifications of another assertion. '
    'Atomicity correction must keep measures together with their periods, bases and attribution. '
    'Canonical source quotations are retained in the audit; this review wire references the exact '
    'source.parts[].source_text by part_id instead of repeating those full passages per meaning. '
    'If meaning_resolution is supplied, independently adjudicate EVERY finding disposition against '
    'the complete owned source and CURRENT union. It is a proposal, never an acceptance. '
    'Disposition referenced_meaning_ids refer ONLY to meaning_resolution.before_resolution_meanings, '
    'the explicitly labelled immutable PRE-EDIT namespace. Atomic splits can renumber the final '
    'current_meanings; never reinterpret those historical IDs in the current namespace. Follow '
    'the exact before assertion and owning part to the current union by its actual preserved meaning. '
    'already-covered references for actual assertion coverage, outside-scope reasons for genuine '
    'section relevance, and corrected copy for source truth and preservation. Reject a disguised '
    'missing condition or dropped selected assertion. Preserve the intended selected union in '
    'meaning_revision_base AND meaning_resolution.decisions_before, including assertions added '
    'by the first revision, with unsupported wording corrected to its actual source scope. '
    'Report any remaining genuine defect; never invent another requirement merely because the '
    'prior review rejected the candidate.'
)


def selection_wire(values):
    """Reference each complete source passage once without changing canonical audit data."""
    if values is None:
        return None
    if isinstance(values, dict):
        return {**values, 'decisions': selection_wire(values['decisions'])} if 'decisions' in values else dict(values)
    return [{**decision, 'required_meanings': [
        {key: value for key, value in meaning.items() if key != 'source_quote' or not value}
        for meaning in decision.get('required_meanings', [])]}
        if 'required_meanings' in decision else dict(decision) for decision in values]


def review_current_selection(gateway, source, values, rules, review, *, attempt,
                             meaning_revision_base, inventory_revision_base,
                             binding_budget, cancelled=None, meaning_resolution=None):
    """At most one shared binding re-review; bound semantic rejections are final verdicts."""
    from .introduction_audience import complete_response
    inventory = [{key: value for key, value in row.items() if key != 'source_quote'}
                 for row in current_meanings(values)]
    resolution = dict(meaning_resolution) if meaning_resolution is not None else None
    if resolution is not None:
        resolution['decisions_before'] = selection_wire(resolution['decisions_before'])
    payload = dict(source=source, decisions=selection_wire(values), current_meanings=inventory,
                   current_selection_digest=selection_digest(review, values),
                   meaning_revision_base=selection_wire(meaning_revision_base),
                   inventory_revision_base=selection_wire(inventory_revision_base),
                   meaning_resolution=resolution,
                   current_meaning_unions=[dict(part_id=decision['part_id'], meaning_ids=[
                       row['meaning_id'] for row in inventory if row['part_id'] == decision['part_id']])
                       for decision in values if decision['include']])
    for re_review in (False, True):
        record = dict(round=attempt + 1, re_review=re_review,
                      selection_digest=payload['current_selection_digest'], decisions=values,
                      status='pending')
        review.plan_audits.append({'introduction_audience_review': record})
        try:
            verdict = complete_response(gateway, [
                {'role': 'system', 'content': rules + _BINDING_RULES},
                untrusted_document_message(json.dumps(payload, ensure_ascii=False))],
                IntroductionAudienceReview, cancelled=cancelled)
        except (LLMError, ValueError, CancelledError) as exc:
            record.update(status='cancelled' if isinstance(exc, CancelledError) else 'failed',
                          error_type=type(exc).__name__)
            raise
        errors = binding_errors(verdict, payload)
        record.update(review=verdict.model_dump(mode='json'), binding_errors=errors,
                      status='invalid_binding' if errors else 'bound')
        if not errors:
            return verdict
        if binding_budget['used']:
            raise ValueError('Introduction independent review has invalid current-draft binding: ' + '; '.join(errors))
        binding_budget['used'] = True
        payload['previous_unbound_review'] = verdict.model_dump(mode='json')
        payload['review_binding_errors'] = errors
    raise AssertionError('Unreachable review binding budget')
