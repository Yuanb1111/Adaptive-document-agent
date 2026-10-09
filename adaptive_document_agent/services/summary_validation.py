"""Verify complete source assignment and exact model decisions, never importance."""
from adaptive_document_agent.models import PipelineResult
from adaptive_document_agent.models.executive_brief import ExecutiveBrief, ExecutiveBriefItem, BriefQuote
from adaptive_document_agent.models.summary import SummaryReview
from adaptive_document_agent.services.executive_brief import validate_executive_brief
from adaptive_document_agent.services.source_quotes import normalize_quote
from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator


def fact_errors(fact, result: PipelineResult, source_text: str, page: int) -> list[str]:
    errors = []
    if fact.source_pages != [page]:
        errors.append('Each reading fact needs its exact source page')
    if normalize_quote(fact.source_quote) not in normalize_quote(source_text):
        errors.append('Quote is absent from the assigned source part')
    brief = ExecutiveBrief(title='Summary', items=[ExecutiveBriefItem(label=fact.label, text=fact.text,
        evidence=[BriefQuote(page=page, text=fact.source_quote)])])
    errors.extend(validate_executive_brief(brief, result, excerpts={page: source_text}))
    return errors


def reading_errors(review: SummaryReview, result: PipelineResult, *, complete_scope=True) -> list[str]:
    errors = []
    if not review.source_pages or not review.source_blocks or not review.parts:
        errors.append('Complete Summary reading requires supplied source pages, blocks and parts')
    if (review.document_id, review.document_sha256) != (result.document.document_id, result.document.sha256):
        errors.append('Summary reading belongs to a different document')
    pages = {p.page_number: p.text for p in result.document.pages}
    if len(set(review.source_pages)) != len(review.source_pages) or not set(review.source_pages) <= pages.keys():
        errors.append('Summary reading has invalid source pages')
    if complete_scope:
        from .summary_source import summary_scope
        try:
            if review.source_pages != summary_scope(result, review.scope_ranges):
                errors.append('Summary reading omits or changes its complete source scope')
        except ValueError as exc:
            errors.append(str(exc))
    blocks = {b.id: b for b in review.source_blocks}
    if len(blocks) != len(review.source_blocks):
        errors.append('Summary source block IDs repeat')
    for page in review.source_pages:
        spans = sorted((b for b in review.source_blocks if b.page == page), key=lambda b: b.char_start)
        end = 0
        for block in spans:
            if ((complete_scope and block.char_start != end) or block.char_start < 0
                    or block.char_end <= block.char_start
                    or block.text != pages.get(page, '')[block.char_start:block.char_end]):
                errors.append('Summary source blocks skip, overlap or alter source text')
            end = block.char_end
        if complete_scope and end != len(pages.get(page, '')):
            errors.append('Summary page was not completely supplied')
    if any(b.page not in review.source_pages for b in review.source_blocks):
        errors.append('Summary source block is outside the selected scope')
    ids = set()
    for part in review.parts:
        if part.id in ids:
            errors.append('Summary part IDs repeat')
        ids.add(part.id)
        block = blocks.get(part.block_id)
        if block is None:
            errors.append('Summary part cites an unknown source block')
            continue
        lines = block.text.splitlines(keepends=True)
        if not 1 <= part.start_line <= part.end_line <= len(lines):
            errors.append('Summary part has an invalid source line range')
            continue
        source = ''.join(lines[part.start_line-1:part.end_line])
        if part.source_page != block.page or part.source_text != source:
            errors.append('Summary part changed source text or page')
        if not part.title.strip() or not part.reading_note.strip():
            errors.append('Every Summary part needs a title and reading explanation')
        if PresentationPlanValidator._numbers(part.title + ' ' + part.reading_note) - PresentationPlanValidator._numbers(source):
            errors.append('Summary part title/reading note contains unsupported numbers')
        if part.role == 'layout' and part.facts:
            errors.append('Layout-only material cannot supply factual slide copy')
        for fact in part.facts:
            errors.extend(fact_errors(fact, result, source, block.page))
    for block in review.source_blocks:
        spans = sorted((p for p in review.parts if p.block_id == block.id), key=lambda p: p.start_line)
        end = 0
        for part in spans:
            if part.start_line != end + 1:
                errors.append('Summary parts skip or overlap supplied source lines')
            end = part.end_line
        if end != len(block.text.splitlines(keepends=True)):
            errors.append('Summary block was not completely read and assigned')
    return list(dict.fromkeys(errors))


def presentation_errors(review: SummaryReview, slide_pages, result: PipelineResult) -> list[str]:
    errors = reading_errors(review, result)
    parts = {p.id: p for p in review.parts}
    used, copy_seen, page_ids = set(), set(), set()
    for page in slide_pages:
        if page.id in page_ids:
            errors.append('Summary slide IDs repeat')
        page_ids.add(page.id)
        if not page.title.strip() or not page.source_section.strip():
            errors.append('Summary slide needs a title and source section')
        # Two tiny sentences must not become a separate, nearly empty slide.
        if sum(len(item.text.strip()) for item in page.items) < 180:
            errors.append('Sparse Summary slide: merge its supported facts or omit it; never pad copy')
        for item in page.items:
            from .presentation_brief import is_technical_copy
            if is_technical_copy(item.text):
                errors.append('Summary slide copy would be withheld by audience layout checks')
            known = [parts[pid] for pid in item.part_ids if pid in parts]
            if len(known) != len(item.part_ids) or len(set(item.part_ids)) != len(item.part_ids):
                errors.append('Summary slide item cites unknown or repeated parts')
                continue
            if any(part.role != 'content' for part in known):
                errors.append('Summary slide item cites layout-only material')
            if not known or not any(f.source_quote == item.source_quote and f.source_pages == item.source_pages
                                    for part in known for f in part.facts):
                errors.append('Summary slide quote must retain a fact from the complete reading')
            for pid in item.part_ids:
                part = parts[pid]
                # Each referenced part must genuinely contribute evidence.
                if not any(f.source_quote == item.source_quote for f in part.facts):
                    errors.append('Summary slide item claims a part without its evidence')
            used.update(item.part_ids)
            key = normalize_quote(item.text)
            if key in copy_seen:
                errors.append('Summary presentation repeats a finding')
            copy_seen.add(key)
            if known:
                errors.extend(fact_errors(item, result, known[0].source_text, known[0].source_page))
        supporting = ' '.join(item.source_quote for item in page.items)
        if PresentationPlanValidator._numbers(page.title) - PresentationPlanValidator._numbers(supporting):
            errors.append('Summary slide title contains unsupported numbers')
    decisions = {d.part_id: d for d in review.decisions}
    if len(decisions) != len(review.decisions) or set(decisions) != set(parts):
        errors.append('Decide every read Summary part exactly once')
    for pid, decision in decisions.items():
        if not decision.reason.strip() or (decision.decision == 'include') != (pid in used):
            errors.append('Summary include/omit decision does not match rendered evidence: ' + pid)
    return list(dict.fromkeys(errors))
