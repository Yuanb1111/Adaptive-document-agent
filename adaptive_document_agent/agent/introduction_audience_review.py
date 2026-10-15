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
)


def review_current_selection(gateway, source, values, rules, review, *, attempt,
                             meaning_revision_base, inventory_revision_base,
                             binding_budget, cancelled=None):
    """At most one shared binding re-review; bound semantic rejections are final verdicts."""
    from .introduction_audience import complete_response
    payload = dict(source=source, decisions=values, current_meanings=current_meanings(values),
                   current_selection_digest=selection_digest(review, values),
                   meaning_revision_base=meaning_revision_base,
                   inventory_revision_base=inventory_revision_base)
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
