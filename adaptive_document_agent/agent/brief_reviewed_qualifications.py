"""Bind a newly requested numeric qualification to its own reviewer-cited passage."""
import re

from pydantic import BaseModel, ConfigDict, Field
from adaptive_document_agent.models.executive_brief import BRIEF_EVIDENCE_LIMIT
from adaptive_document_agent.services.brief_table_evidence import canonical_quantity
from adaptive_document_agent.services.executive_brief import _quantities, _MONEY_QUANTITY, _QUANTITY
from adaptive_document_agent.services.number_words import cardinal_claim_text


class ReviewedQualification(BaseModel):
    model_config = ConfigDict(extra='forbid')
    claim: str = Field(min_length=1, max_length=550, description='Exact complete clause in this item’s corrected body.')
    source_ref: str = Field(min_length=1, description='The offered literal passage that supports this clause.')


_REF = r'p(?P<page>\d+)_b(?P<block>\d+)'
_CITATION = re.compile(r'\b' + _REF + r'\b(?:\s*[–—-]\s*\bp(?P<end_page>\d+)_b(?P<end>\d+)\b)?')
_RELATION = (r'(?P<relation>\b(?:more than|greater than|over|less than|fewer than|under|at least|at most)\b'
             r'|(?<![<>=])(?:<=|>=|[<>≤≥])(?![<>=]))\s*')
_DURATION_UNIT = {'yr':'year', 'mo':'month', 'wk':'week', 'hr':'hour'}
_THRESHOLD = re.compile(_RELATION + r'(?P<number>\d+(?:\.\d+)?)(?:\s+|\s*[-‑]\s*|(?=yrs?\b|mos?\b|wks?\b|hrs?\b))'
                        r'(?P<unit>years?|months?|weeks?|days?|hours?|yrs?|mos?|wks?|hrs?)\b', re.I)
_RELATIONS = {'over': 'more than', 'greater than': 'more than', '>': 'more than',
              'under': 'less than', 'fewer than': 'less than', '<': 'less than',
              '<=': 'at most', '≤': 'at most', '>=': 'at least', '≥': 'at least'}
_RATE_BOUND = re.compile(_RELATION + r'(?P<number>\d+(?:\.\d+)?)\s*(?:%|per\s+cent\b|percent\b)', re.I)
_ITEM_REF = re.compile(r'\bi(?P<item>\d+)_q(?P<quote>\d+)\b')


def reviewed_refs(reason):
    """Expand only bounded, forward, same-page physical block ranges."""
    refs = []
    for match in _CITATION.finditer(reason):
        first = int(match['block'])
        last = int(match['end']) if match['end'] else first
        if match['end_page'] == match['page'] and 0 <= last - first < BRIEF_EVIDENCE_LIMIT:
            refs.extend(f'p{match["page"]}_b{n}' for n in range(first, last + 1))
        else:
            refs.append(f'p{match["page"]}_b{first}')
            if match['end_page']:
                refs.append(f'p{match["end_page"]}_b{last}')
    return list(dict.fromkeys(refs))


def _threshold(match):
    relation = match['relation'].casefold()
    unit = match['unit'].casefold().rstrip('s')
    return _RELATIONS.get(relation, relation), match['number'], _DURATION_UNIT.get(unit, unit)


def _typed_quantities(text):
    return {canonical_quantity(*q) for q in _quantities(text) if q[0] or q[2] in {'%', 'percent'}}


def _rate_bound(match):
    relation = match['relation'].lower()
    return _RELATIONS.get(relation, relation), match['number']


def _bounds(texts, pattern, identity):
    return {identity(match) for text in texts for match in pattern.finditer(cardinal_claim_text(text))}


def narrower_qualification_options(previous_refs, original_options, alias_options):
    """Project an authorized joined passage's values onto its actual constituent proofs."""
    from adaptive_document_agent.services.source_quotes import normalize_quote
    fields = ('typed_quantities', 'duration_thresholds', 'percentage_thresholds')
    chosen = {ref:{**original_options[ref], **{k:list(original_options[ref].get(k, [])) for k in fields}}
              for ref in previous_refs if ref in original_options}
    for ref, alias in alias_options.items():
        remaining = {k:set(map(tuple, alias.get(k, []))) for k in fields}
        for target in chosen.values():
            proof = target['literal_proof']
            if target['page'] != alias['page'] or normalize_quote(proof) not in normalize_quote(alias['literal_proof']):
                continue
            supported = dict(typed_quantities=_typed_quantities(proof),
                duration_thresholds=_bounds([proof], _THRESHOLD, _threshold),
                percentage_thresholds=_bounds([proof], _RATE_BOUND, _rate_bound))
            for key in fields:
                matched = supported[key] & set(map(tuple, alias.get(key, [])))
                target[key] = sorted(set(map(tuple, target[key])) | matched)
                remaining[key] -= matched
            bounded = {number for _,number in target['percentage_thresholds']}
            target['typed_quantities'] = [q for q in target['typed_quantities']
                                          if not (q[2] == '%' and q[1] in bounded)]
        if any(remaining.values()) or not chosen:
            chosen[ref] = {**alias, **{k:sorted(v) for k,v in remaining.items()}}
    return chosen


def qualification_quantity_errors(text, ref, options):
    """An existing typed value cannot be moved into a different source's part."""
    masked, errors = mask_reviewed_qualifications(text, [dict(claim=text, source_ref=ref)], options)
    if _typed_quantities(masked) or _bounds([masked], _THRESHOLD, _threshold) or _bounds([masked], _RATE_BOUND, _rate_bound):
        errors.append(f'The authored clause contains an amount, rate or duration threshold outside its own source {ref}.')
    return errors


def reviewed_alias_options(brief, failures, result, excerpts):
    """Resolve reviewer aliases against the exact candidate and the reviewer's joined passage order."""
    from adaptive_document_agent.services.source_quotes import continuous_quote_passages, normalize_quote
    pages = {page.page_number:page.text for page in result.document.pages}
    options = {}
    for index, reasons in failures.items():
        passages = continuous_quote_passages(brief.items[index].evidence, pages)
        for offset, passage in enumerate(passages):
            ref = f'i{index}_q{offset}'
            requested = [reason for reason in reasons if ref in {m[0] for m in _ITEM_REF.finditer(reason)}]
            if not requested or normalize_quote(passage.text) not in normalize_quote(excerpts.get(passage.page, '')):
                continue
            amounts = _typed_quantities(passage.text) & set().union(*(_typed_quantities(r) for r in requested))
            requested_rates = _bounds(requested, _RATE_BOUND, _rate_bound)
            rates = _bounds([passage.text], _RATE_BOUND, _rate_bound) & requested_rates
            durations = _bounds([passage.text], _THRESHOLD, _threshold) & _bounds(requested, _THRESHOLD, _threshold)
            # A limit in the reviewer request can only be shown with the
            # matching source relation. A threshold is not an exact observation.
            requested_bounds = {number for _, number in requested_rates}
            amounts = {q for q in amounts if not (q[2] == '%' and q[1] in requested_bounds)}
            body = brief.items[index].text
            if not (amounts - _typed_quantities(body) or durations - _bounds([body], _THRESHOLD, _threshold)
                    or rates - _bounds([body], _RATE_BOUND, _rate_bound)):
                continue
            options.setdefault(index, {})[ref] = dict(page=passage.page, literal_proof=passage.text,
                typed_quantities=sorted(amounts), duration_thresholds=sorted(durations),
                percentage_thresholds=sorted(rates))
    return options


def qualification_options(failures, brief, catalog, excerpts):
    options = {}
    for index, reasons in failures.items():
        citations = {(q.page, q.text) for q in brief.items[index].evidence}
        rows = {}
        for ref in dict.fromkeys(ref for reason in reasons for ref in reviewed_refs(reason)):
            block = catalog.get(ref)
            if not block or (block['page'], block['text']) not in citations or block['text'] not in excerpts.get(block['page'], ''):
                continue
            proof = block['text']
            requested = [reason for reason in reasons if ref in reviewed_refs(reason)]
            amounts = _typed_quantities(proof) & set().union(*(_typed_quantities(reason) for reason in requested))
            thresholds = {_threshold(m) for m in _THRESHOLD.finditer(cardinal_claim_text(proof))}
            thresholds &= {_threshold(m) for reason in requested for m in _THRESHOLD.finditer(cardinal_claim_text(reason))}
            if amounts or thresholds:
                rows[ref] = dict(page=catalog[ref]['page'], literal_proof=proof,
                                 typed_quantities=sorted(amounts), duration_thresholds=sorted(thresholds))
        if rows:
            options[index] = rows
    return options


def mask_reviewed_qualifications(text, bindings, options):
    """Mask only licensed occurrences inside exact, nonoverlapping bound body clauses."""
    replacements, errors = [], []
    for binding in bindings:
        claim, ref = binding['claim'], binding['source_ref']
        if ref not in options or not claim.strip() or text.count(claim) != 1:
            errors.append('Source qualification needs an offered reference and a unique exact clause in this item.')
            continue
        start, end = text.index(claim), text.index(claim) + len(claim)
        if any(start < b and a < end for a, b, _ in replacements):
            errors.append('Source qualification clauses must not overlap.')
            continue
        amounts = set(map(tuple, options[ref]['typed_quantities']))
        thresholds = set(map(tuple, options[ref]['duration_thresholds']))
        rates = set(map(tuple, options[ref].get('percentage_thresholds', [])))
        normalized = cardinal_claim_text(claim)
        if options[ref].get('original_rate_comparisons'):
            from .brief_qualification_comparisons import mask_comparison_baselines
            normalized = mask_comparison_baselines(normalized, options[ref]['original_rate_comparisons'])
        masked = _THRESHOLD.sub(lambda m: ' ' if _threshold(m) in thresholds else m[0], normalized)
        masked = _RATE_BOUND.sub(lambda m: ' ' if _rate_bound(m) in rates else m[0], masked)
        def mask_amount(match):
            displayed = _typed_quantities(match[0])
            return ' ' if displayed and displayed <= amounts else match[0]
        masked = _QUANTITY.sub(mask_amount, _MONEY_QUANTITY.sub(mask_amount, masked))
        replacements.append((start, end, masked))
    for start, end, replacement in sorted(replacements, reverse=True):
        text = text[:start] + replacement + text[end:]
    return text, errors
