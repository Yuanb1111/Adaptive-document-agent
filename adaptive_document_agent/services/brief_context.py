"""Restore explicit relationships lost when a cited finding was shortened.

This is an extractive display adapter, not semantic extraction or calculation.
Original brief records and source pages are never mutated. Unknown grammar and
ambiguous definitions remain unchanged rather than acquiring guessed context.
"""
from dataclasses import dataclass
from decimal import Decimal
import re

from adaptive_document_agent.models.executive_brief import BriefQuote, ExecutiveBriefItem

_CADENCE = r'hourly|daily|weekly|monthly|quarterly|annually|annual|yearly'
_DEFINITION = re.compile(
    rf'(?P<metric>(?:[A-Za-z][\w-]*\s+){{1,8}}[A-Za-z][\w-]*)\s+'
    rf'(?:refers\s+to|is\s+defined\s+as|means)\s+(?:the\s+)?(?:average\s+)?'
    rf'(?P<cadence>{_CADENCE})\b', re.I)
_NAMED_RATE = re.compile(r'\b(?P<metric>(?:[A-Za-z][\w-]*\s+){0,10}?rate)\b', re.I)
_QUOTED_RATE = re.compile(
    rf'\b(?P<cadence>{_CADENCE})\s+(?:average\s+)?'
    r'(?P<metric>(?:[A-Za-z][\w-]*\s+){0,6}?rate)\b', re.I)
# Postfix denominators must belong to a direct metric/value predicate. A
# bounded arbitrary window could borrow another measure's denominator.
_POSTFIX_RATE = re.compile(
    r'\b(?P<metric>(?:[A-Za-z][\w-]*\s+){0,7}?rate)\s+'
    r'(?:was|is|remains|of|at|will\s+be)\s+(?:approximately\s+|about\s+)?'
    r'(?:[A-Z]{3}\s*|[$€£¥]\s*)?[+-]?\d+(?:,\d{3})*(?:\.\d+)?'
    r'(?:\s+(?!(?:per|and|or|while|but)\b)[A-Za-z][\w-]*){0,4}\s*'
    r'(?:per\s+|/)\s*(?P<denominator>hour|day|week|month|quarter|year)\b', re.I)
_DENOMINATOR_CADENCE = {'hour': 'hourly', 'day': 'daily', 'week': 'weekly',
                      'month': 'monthly', 'quarter': 'quarterly', 'year': 'yearly'}
_OUTCOME = re.compile(
    r'(?<![\w.])(?P<number>\d+(?:\.\d+)?)\s*(?:[-–‑]\s*)?'
    r'(?P<unit>seconds?|minutes?|hours?|days?|weeks?|months?|years?|%|percent\b|times?\b|x\b)', re.I)
_CONDITION = re.compile(r'\b(?:if|with|without|assuming|scenario)\b', re.I)
_SENTENCE_BREAK = re.compile(r'(?<=[.!?])\s+(?=[A-Z])')



@dataclass(frozen=True)
class ContextualBriefCopy:
    text: str
    evidence: list[BriefQuote]
    conditions: str = ''


def _normalized(text: str) -> str:
    return ' '.join(text.casefold().split())


def _sentences(text: str) -> list[str]:
    # A period inside a decimal is not a sentence boundary. Keep abbreviations
    # together when there is no following uppercase sentence start.
    return [part.strip() for part in _SENTENCE_BREAK.split(' '.join(text.split())) if part.strip()]


def _outcomes(text: str) -> dict[str, set[str]]:
    values: dict[str, set[str]] = {}
    for match in _OUTCOME.finditer(text):
        # A dated reporting window is context, not a conditional outcome.
        # Keep genuine durations (including buffers and assumed horizons); only
        # exclude an explicit period-ending date immediately after the unit.
        if re.match(
            r'\s+ended\s+(?:(?:January|February|March|April|May|June|July|August|'
            r'September|October|November|December)\s+\d{1,2},?\s+\d{4}'
            r'|\d{4}-\d{2}-\d{2}|\d{1,2}\s+(?:January|February|March|April|May|June|'
            r'July|August|September|October|November|December)\s+\d{4})\b',
            text[match.end():], re.I,
        ):
            continue
        unit = match['unit'].casefold().rstrip('s')
        unit = '%' if unit == 'percent' else unit
        values.setdefault(unit, set()).add(str(Decimal(match['number']).normalize()))
    return values


def _emphasize_whole_operand(sentence: str) -> str:
    """Make a literal part-versus-whole contrast explicit, without new amounts.

    Only repeated, exact noun phrases in the same conditional list qualify:
    "take into account 25% of the reserve" / "take into account the reserve".
    Nothing is added for an unmatched operand or a missing/unknown allocation.
    """
    partial = re.compile(
        r'(?P<verb>take\s+into\s+account)\s+(?P<share>\d+(?:\.\d+)?\s*%)\s+of\s+'
        r'(?P<operand>the\s+[^,();.]+)', re.I)
    for match in list(partial.finditer(sentence)):
        if not 0 < float(match['share'].rstrip('%').strip()) < 100:
            continue
        operand = match['operand'].strip()
        # Require a clause boundary: do not upgrade "the reserve earmarked for
        # maintenance" when only "the reserve" was used in the partial case.
        whole = re.compile(r'(?P<verb>take\s+into\s+account)\s+' + re.escape(operand)
                           + r'(?=\s*[,;)])', re.I)
        sentence = whole.sub(lambda whole_match: whole_match['verb'] + ' all of ' + operand, sentence)
    return sentence


def _relation_subject(text: str) -> str | None:
    """Bind an explicit pre-outcome subject, never an arbitrary shared token.

    This deliberately recognizes a small grammatical shape rather than treating
    contextual words ("coverage", "reserve", "operations") as an entity. Unknown
    or paraphrased subjects remain untouched for semantic authoring to resolve.
    """
    first_outcome = _OUTCOME.search(text)
    if first_outcome is None:
        return None
    prefix = text[:first_outcome.start()]
    attribution = re.search(r'\bestimate(?:d|s)?\s+that\s+', prefix, re.I)
    if attribution:
        prefix = prefix[attribution.end():]
    elif re.match(r'\s*assuming\b', prefix, re.I):
        if ',' not in prefix:
            return None
        prefix = prefix.split(',', 1)[1]
    prefix = re.sub(r'^(?:(?:the|our|its|their|a|an|estimated)\s+)+', '', prefix.strip(), flags=re.I)
    predicate = re.search(r'\b(?:is|was|were|are|lasts?|will|could|would|can|may|might|must|should|'
                          r'has|have|had|remains?|remained|equals?|totaled|totals?|covers?)\b', prefix, re.I)
    if predicate is None:
        return None
    subject = _normalized(prefix[:predicate.start()]).strip(' ,:')
    return subject if subject and not re.search(r'[;:]', subject) else None


def _complete_scenarios(text: str, evidence: list[BriefQuote], pages=None) -> str:
    from .source_quotes import continuous_quote_texts
    passages = continuous_quote_texts(evidence, pages) if pages is not None else [q.text for q in evidence]
    source_sentences = list(dict.fromkeys(sentence for passage in passages for sentence in _sentences(passage)))
    shown = _sentences(text)
    for position, summary in enumerate(shown):
        # An already-literal independent sentence must not be rewritten from
        # another sentence that happens to repeat its values or generic terms.
        if any(_normalized(summary) == _normalized(source) for source in source_sentences):
            shown[position] = _emphasize_whole_operand(summary)
            continue
        claimed = _outcomes(summary)
        subject = _relation_subject(summary)
        candidates = []
        for source in source_sentences:
            if (len(_CONDITION.findall(source)) < 2
                    or subject is None or subject != _relation_subject(source)):
                continue
            outcomes = _outcomes(source)
            # The summary must already select at least two outcomes of this
            # relation. A nearby scenario or a lone coincident number cannot
            # authorize adding a different subject's alternatives.
            if any(len(values) >= 2 and len(values & claimed.get(unit, set())) >= 2
                   for unit, values in outcomes.items()):
                candidates.append(source)
        if len(candidates) != 1:
            continue
        # Restore the whole cited sentence, including the shared premise,
        # baseline, intermediate cases and qualifications. Do not assemble a
        # new sentence from unrelated numeric matches or truncate to fit.
        replacement = _emphasize_whole_operand(candidates[0])
        # A paraphrase can contain independent qualitative qualifications at
        # any position. Deterministic extraction cannot prove that replacing
        # it is lossless. Retain the authored sentence and append the complete
        # literal comparison; the renderer measures/paginates the added copy.
        shown[position] = summary + ' Source scenarios: ' + replacement
    return ' '.join(shown)


def _canonical_rate_name(metric: str) -> str:
    # Strip only bounded grammatical introductions and explicit modifiers at
    # the beginning. Distinct names such as 'battery processing rate' remain
    # distinct; no suffix/subsequence equivalence is inferred.
    metric = _normalized(metric)
    metric = re.sub(r'^(?:assuming(?: that)?|given(?: that)?|provided that|if|when)\s+', '', metric)
    metric = re.sub(rf'^(?:(?:our|the|its|their|a|an|average|{_CADENCE})\s+)+', '', metric)
    return metric


def _rate_references(text: str) -> dict[str, list[tuple[int, int]]]:
    references: dict[str, list[tuple[int, int]]] = {}
    for match in _NAMED_RATE.finditer(text):
        metric = _canonical_rate_name(match['metric'])
        # Display sentences use normalized whitespace, so the retained exact
        # name is the suffix of the bounded reference. Quoted references only
        # use these keys, not their offsets.
        references.setdefault(metric, []).append((match.end() - len(metric), match.end()))
    return references


def _rate_definitions(text: str):
    for sentence in _sentences(text):
        if len(sentence) > 1800:
            continue  # Preserve the quote limit; never cut a definition in half.
        for match in _DEFINITION.finditer(sentence):
            metric = _canonical_rate_name(match['metric'])
            yield metric, match['cadence'].casefold(), sentence
            alternative = re.match(rf'\s*(?:or|/)\s*(?P<cadence>{_CADENCE})\b',
                                   sentence[match.end():], re.I)
            if alternative:
                # Expose both candidates to the ambiguity guard, never choose
                # the first denominator merely because it occurs first.
                yield metric, alternative['cadence'].casefold(), sentence


def _restore_cadence(text: str, evidence: list[BriefQuote], pages: dict[int, str]):
    definitions: dict[str, list[tuple[str, int, str]]] = {}
    cited = {quote.page for quote in evidence}
    adjacent = {page + offset for page in cited for offset in (-1, 0, 1)}
    quoted = ' '.join(quote.text for quote in evidence)
    cited_names = _rate_references(quoted)
    displayed_names = _rate_references(text)
    for page in sorted(adjacent & pages.keys()):
        for metric, cadence, sentence in _rate_definitions(pages[page]):
            # Preserve the source's exact metric name. Similar labels and
            # document-wide definitions are not enough to resolve a denominator.
            if metric in displayed_names and metric in cited_names:
                definitions.setdefault(metric.casefold(), []).append((cadence, page, sentence))
    for quote in evidence:
        for match in _QUOTED_RATE.finditer(quote.text):
            metric = _canonical_rate_name(match['metric'])
            if metric in displayed_names:
                definitions.setdefault(metric, []).append((match['cadence'].casefold(), quote.page, quote.text))
        for match in _POSTFIX_RATE.finditer(quote.text):
            metric = _canonical_rate_name(match['metric'])
            if metric in displayed_names:
                cadence = _DENOMINATOR_CADENCE[match['denominator'].casefold()]
                definitions.setdefault(metric, []).append((cadence, quote.page, quote.text))
    additions = []
    for metric, matches in definitions.items():
        if len({cadence for cadence, _, _ in matches}) != 1:
            continue
        cadence, page, sentence = matches[0]
        spans = _rate_references(text).get(metric, [])
        if not spans:
            continue
        start, end = spans[0]
        nearby = text[max(0, start - 24):end + 40]
        if re.search(rf'\b(?:{_CADENCE})\b|(?:\bper\s+|/)\s*(?:hour|day|week|month|quarter|year)\b', nearby, re.I):
            continue
        quote = BriefQuote(page=page, text=sentence)
        if not any(q.page == page and _normalized(sentence) in _normalized(q.text) for q in evidence):
            if len(evidence) + len(additions) >= 4:
                continue  # Do not exceed the author's bounded evidence budget.
            additions.append(quote)
        text = text[:start] + cadence + ' ' + text[start:]
    return text, additions


def preserve_brief_context(item: ExecutiveBriefItem, pages: dict[int, str]) -> ContextualBriefCopy:
    """Return complete display copy and the literal evidence used to restore it.

    Call only after normal item-bound quote/quantity validation. Rate context
    additionally has to be a literal contiguous quotation of a cited or adjacent
    source page. The authoring schema's copy budget never truncates display text;
    the existing renderer paginates this complete copy at its fixed line spacing.
    """
    text = item.text if item.comparison_table else _complete_scenarios(item.text, item.evidence, pages)
    text, additions = _restore_cadence(text, item.evidence, pages)
    evidence = [*item.evidence, *additions]
    conditions = ''
    if item.comparison_table:
        # A model-selected comparison can quote each scenario while missing the
        # immediately preceding shared assumption. Restore only a literal
        # conditional clause directly adjoining the first cited scenario.
        starts = []
        for quote in item.evidence:
            if not (_CONDITION.search(quote.text) and _OUTCOME.search(quote.text)):
                continue
            source = ' '.join(pages.get(quote.page, '').split())
            start = source.find(' '.join(quote.text.split()))
            if start >= 0:
                starts.append((quote.page, start, source))
        if starts:
            page, start, source = min(starts, key=lambda entry: entry[:2])
            prefix = source[max(0, start - 1800):start].strip()
            last = _sentences(prefix)[-1] if prefix else ''
            match = re.search(r'\bassuming\b.+', last, re.I)
            if match and len(match.group()) <= 700:
                conditions = match.group().strip()
                if _normalized(conditions) not in _normalized(text):
                    evidence.append(BriefQuote(page=page, text=conditions))
                else:
                    conditions = ''
    return ContextualBriefCopy(text, evidence, conditions)


def adjacent_definition_excerpts(pages: dict[int, str], selected: dict[int, str]) -> dict[int, str]:
    """Retrieve bounded literal definitions next to model-selected source pages.

    No additional model call or document-type retrieval rule is needed. The
    original page number is retained; only explicitly named, shared metrics
    allow a neighboring page to enter the brief's evidence context.
    """
    anchors = _rate_references(' '.join(selected.values()))
    adjacent = {page + offset for page in selected for offset in (-1, 1)}
    excerpts = {}
    for page in sorted((adjacent & pages.keys()) - selected.keys()):
        normalized_page = ' '.join(pages[page].split())
        spans = []
        for metric, _, sentence in _rate_definitions(pages[page]):
            if metric not in anchors:
                continue
            start = normalized_page.find(sentence)
            if start >= 0:
                spans.append((start, start + len(sentence)))
        if not spans:
            continue
        start, end = min(s[0] for s in spans), max(s[1] for s in spans)
        if end - start <= 4000:
            excerpts[page] = normalized_page[start:end]
        if len(excerpts) == 6:
            break
    return excerpts
