"""Bounded, page-preserving source retrieval for interpretation of results.

Lexical overlap and source proximity choose reading candidates only. The model
decides whether those passages explain a result; retrieval never asserts a cause.
"""

from dataclasses import dataclass
import re

from adaptive_document_agent.models import AnalysisResult, Observation, ParsedDocument, SourceEvidence


@dataclass(frozen=True)
class SourceExcerpt:
    page: int
    text: str
    start_char: int
    confidence: float

    def payload(self) -> dict[str, object]:
        return {"page": self.page, "text": self.text, "start_char": self.start_char,
                "end_char": self.start_char + len(self.text)}


def _terms(result: AnalysisResult, observations: list[Observation]) -> list[str]:
    labels = []
    for item in observations:
        labels.extend([item.metric_original, item.metric_canonical or "", item.parent_section or ""])
        labels.extend(item.category_dimensions.values())
    if not labels:
        labels = [result.title, *(source.row_label or "" for source in result.evidence)]
    terms = set()
    for label in labels:
        label = " ".join(label.casefold().split())
        if len(label) >= 3:
            terms.add(label)
        terms.update(re.findall(r"[a-z][a-z0-9]{2,}|[\u3400-\u9fff]{2,}", label))
    return sorted(terms, key=lambda term: (-len(term), term))[:48]


def _overlap(text: str, terms: list[str]) -> int:
    lowered = text.casefold()
    return sum(min(len(term), 24) for term in terms if term in lowered)


def _page_windows(text: str, size: int, terms: list[str]) -> list[tuple[int, str]]:
    """Rank intact slices, including later paragraphs of long source pages."""
    if len(text) <= size:
        return [(0, text)] if text.strip() else []
    stride = max(1, size * 3 // 4)
    starts = list(range(0, len(text) - size + 1, stride))
    starts.append(len(text) - size)
    # For equal lexical overlap, prefer text over table padding and digit-only
    # cells. This chooses a reading window, not an explanation or causal claim.
    return sorted(((start, text[start:start + size]) for start in dict.fromkeys(starts)),
                  key=lambda item: (-_overlap(item[1], terms),
                                    -sum(character.isalpha() for character in item[1]), item[0]))


def build_source_contexts(
    results: list[AnalysisResult], observations: list[Observation], document: ParsedDocument | None,
    *, max_total_chars: int = 36_000, max_result_chars: int = 6_000,
    max_excerpt_chars: int = 1_600, max_excerpts: int = 6,
) -> dict[str, list[SourceExcerpt]]:
    """Share a fixed text budget across results; never flatten the document.

Each result gets source pages, neighboring pages, and lexical candidates from
elsewhere in the document. No embeddings, external lookup, or model calls occur.
"""
    contexts: dict[str, list[SourceExcerpt]] = {result.task_id: [] for result in results}
    if not document or not results:
        return contexts
    if min(max_total_chars, max_result_chars, max_excerpt_chars, max_excerpts) <= 0:
        return contexts
    budget = min(max_result_chars, max_total_chars // len(results))
    if budget < 1:
        return contexts
    pages = {page.page_number: page for page in document.pages if page.text.strip()}
    lexical_richness = {number: min(128, len(set(re.findall(r'[a-z]{3,}|[\u3400-\u9fff]{2,}',
                                                         page.text.casefold()))))
                        for number, page in pages.items()}
    by_id = {item.id: item for item in observations}
    for result in results:
        terms = _terms(result, [by_id[oid] for oid in result.input_observation_ids if oid in by_id])
        anchors = {source.page for source in result.evidence}
        scores = {number: _overlap(page.text, terms) for number, page in pages.items()}
        rank = lambda number: (-scores[number], -lexical_richness[number], number)
        direct = sorted(anchors & pages.keys(), key=rank)
        neighbors = sorted(({number + step for number in anchors for step in (-1, 1)} & pages.keys()) - anchors,
                           key=rank)
        other = sorted((number for number in pages if scores[number] > 0
                        and number not in anchors and number not in neighbors), key=rank)
        # Reserve reading opportunities for nearby narrative and remote cross-
        # references, even when the result has many numeric source pages.
        order = list(dict.fromkeys(direct[:1] + neighbors[:1] + other[:1] + direct[1:] + neighbors[1:] + other[1:]))
        # Sharing a large result set across six tiny fragments can cut away
        # the cause and its qualification. Prefer fewer readable passages,
        # still reserving nearby narrative and remote reading opportunities.
        readable_size = min(1200, max_excerpt_chars)
        count = min(max_excerpts, len(order), max(1, budget // readable_size))
        if not count:
            continue
        size = min(max_excerpt_chars, max(1, budget // count))
        remaining = budget
        for number in order[:count]:
            if remaining <= 0:
                break
            page = pages[number]
            windows = _page_windows(page.text, min(size, remaining), terms)
            if not windows:
                continue
            start, text = windows[0]
            contexts[result.task_id].append(SourceExcerpt(number, text, start, page.extraction_quality))
            remaining -= len(text)
    return contexts


def matched_driver_evidence(
    quote: str | None, page: int | None, excerpts: list[SourceExcerpt],
    *, legacy_evidence: list[SourceEvidence] | None = None,
) -> SourceEvidence | None:
    """Accept only a literal quote on a supplied page, allowing PDF whitespace.

The returned text is copied from the source, never copied from model prose.
Legacy callers without parsed pages may cite the result evidence they supplied.
"""
    words = (quote or "").split()
    if not words or page is None:
        return None
    pattern = re.compile(r"\s+".join(re.escape(word) for word in words))
    for excerpt in excerpts:
        if excerpt.page == page and (match := pattern.search(excerpt.text)):
            return SourceEvidence(page=page, text=match.group(), extraction_method="source_text_context",
                                  confidence=excerpt.confidence)
    for source in legacy_evidence or []:
        if source.page == page and (match := pattern.search(source.text or "")):
            return source.model_copy(update={"text": match.group()})
    return None
