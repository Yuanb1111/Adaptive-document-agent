"""Resolve user intent once, using navigation evidence instead of a document template."""

import json

from adaptive_document_agent.models.customization import ReportRequirements
from adaptive_document_agent.services.source_quotes import normalize_quote
from adaptive_document_agent.services.llm.exceptions import LLMTransportError, PrivacyViolationError
from .prompting import load_prompt, untrusted_document_message


def interpret_requirements(gateway, document, instruction):
    """Blank instructions incur no request; failures stay visible and never invent intent."""
    if not instruction or not instruction.strip():
        return None
    instruction = instruction.strip()
    requirements = ReportRequirements(original_request=instruction)
    if gateway is None:
        requirements.interpretation_error = 'A configured model is required to interpret custom report instructions.'
        return requirements
    page_index = [{'page': p.page_number, 'opening_lines': p.text.splitlines()[:12]}
                  for p in document.pages]
    payload = json.dumps({'physical_page_count': document.page_count,
                         'source_sections': [s.model_dump(mode='json') for s in document.outline],
                         'page_index': page_index}, ensure_ascii=False)
    if len(payload) > 180_000:
        requirements.interpretation_error = 'The complete navigation index exceeds the request budget; no sections were silently sampled.'
        return requirements
    messages = [{'role': 'system', 'content': load_prompt('report_requirements.txt')},
                {'role': 'user', 'content': 'Report instructions supplied by the user:\n' + instruction},
                untrusted_document_message(payload)]
    for attempt in range(2):
        try:
            draft = gateway.generate_structured(messages, ReportRequirements, stage='presentation',
                                                allow_repair=False, max_tokens=4096)
            errors = validate_requirements(draft, document, instruction)
            if errors:
                raise ValueError('; '.join(errors))
            draft.original_request = instruction
            draft.copy_translations = {}
            draft.interpretation_error = ''
            return draft
        except PrivacyViolationError:
            raise
        except LLMTransportError as exc:
            requirements.interpretation_error = 'Report instruction interpretation failed: ' + type(exc).__name__
            break
        except (ValueError, RuntimeError) as exc:
            requirements.interpretation_error = type(exc).__name__ + ': ' + str(exc)[:600]
            if attempt == 0:
                messages.append({'role': 'user', 'content': 'Correct the previous interpretation: '
                                 + requirements.interpretation_error + '. Preserve every requested clause. '
                                 'Mark unresolved sections ambiguous rather than guessing page ranges.'})
    return requirements


def validate_requirements(requirements, document, instruction):
    errors = []
    pages = {p.page_number: p for p in document.pages}
    outline = {s.id: s for s in document.outline}
    if not requirements.items:
        errors.append('Nonempty instructions need an explicit interpretation, including unsupported requests')
    if len({r.id for r in requirements.items}) != len(requirements.items):
        errors.append('Requirement IDs must be unique')
    for req in requirements.items:
        if req.request_quote not in instruction:
            errors.append(f'{req.id}: request_quote is not literal user input')
        if req.resolution != 'resolved':
            continue
        if req.kind == 'section_tables' and not req.sections:
            errors.append(f'{req.id}: complete table requests need a bound section')
        if req.kind == 'output_language' and not req.language.strip():
            errors.append(f'{req.id}: requested language is missing')
        if req.kind == 'slide_limit' and req.max_slides is None:
            errors.append(f'{req.id}: slide limit is missing')
        for target in req.sections:
            if not (1 <= target.start_page <= target.end_page <= document.page_count
                    and set(range(target.start_page, target.end_page + 1)) <= set(pages)):
                errors.append(f'{req.id}: invalid physical source range')
                continue
            if target.section_id:
                source = outline.get(target.section_id)
                if source is None or (source.start_page, source.end_page, source.title) != (
                        target.start_page, target.end_page, target.title):
                    errors.append(f'{req.id}: changed or unknown source section')
            else:
                opening = '\n'.join(pages[target.start_page].text.splitlines()[:12])
                quote = normalize_quote(target.start_quote)
                if not quote or quote not in normalize_quote(opening):
                    errors.append(f'{req.id}: section opening needs a literal navigation quote')
                if target.end_page < document.page_count:
                    next_opening = '\n'.join(pages[target.end_page + 1].text.splitlines()[:12])
                    quote = normalize_quote(target.next_section_quote)
                    if not quote or quote not in normalize_quote(next_opening):
                        errors.append(f'{req.id}: section ending needs the next heading quote')
    return errors


def instruction_messages(profile, *, purpose='report'):
    """Trusted user instructions are separate from PDF-derived payloads."""
    requirements = profile.report_requirements
    if not requirements:
        return []
    items = [r.model_dump(mode='json') for r in requirements.items
             if r.resolution == 'resolved' and r.kind not in {'unsupported', 'section_tables', 'output_language'}]
    return [{'role': 'user', 'content': 'Execute these interpreted user report requirements for '
             + purpose + '. Never invent evidence, weaken source validation or suppress caveats. '
             'Whole-section table requests are handled independently by the appendix exporter.\n'
             + json.dumps(items, ensure_ascii=False)}] if items else []


def appendix_pages(requirements):
    return {p for r in requirements.items if r.kind == 'section_tables' and r.resolution == 'resolved'
            for s in r.sections for p in range(s.start_page, s.end_page + 1)} if requirements else set()
