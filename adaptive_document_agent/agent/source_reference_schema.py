"""Transport source quotations as measured references rather than transcriptions."""
from copy import deepcopy
import json
import re
from typing import Annotated, Literal, Union

from pydantic import BaseModel, BeforeValidator, Field, TypeAdapter, create_model, model_validator

from adaptive_document_agent.models.executive_brief import BriefQuote


_LINE_REFERENCE = r'^@lines\[([1-9][0-9]{0,5})(?:-([1-9][0-9]{0,5}))?\]$'


def _page_reference_type(page, refs, existing):
    """Measure an explicit range against numbered physical lines, including line endings."""
    retained = frozenset(existing)
    suggested = TypeAdapter(Literal[refs]) if refs else None
    lines = []
    crlf = set(page.get('crlf_line_endings', ()))
    for index, line in enumerate(page.get('lines', ()), 1):
        prefix = f'{index} | '
        if not isinstance(line, str) or not line.startswith(prefix):
            lines = []
            break
        lines.append(line[len(prefix):] + ('\r\n' if index in crlf else '\n'))

    def validate(value):
        if isinstance(value, str):
            if value in retained or value in refs:
                return value
            match = re.fullmatch(_LINE_REFERENCE, value)
            if match:
                first, last = int(match[1]), int(match[2] or match[1])
                if 1 <= first <= last <= len(lines) and 8 <= len(''.join(lines[first-1:last]).strip()) <= 1800:
                    return value
            if not suggested and not value.startswith('@lines['):
                return value  # Original literal substring on a page without a measured option.
        if suggested:
            return suggested.validate_python(value)
        raise ValueError('Select a continuous range of 8 to 1800 characters on this physical page.')

    if not suggested:
        return Annotated[str, Field(min_length=8, max_length=1800), BeforeValidator(validate)]
    locator = Annotated[str, Field(pattern=_LINE_REFERENCE)]
    wire = Literal[refs] | locator if lines else Literal[refs]
    return Annotated[str, BeforeValidator(validate, json_schema_input_type=wire)]


def referenced_evidence_model(messages, base, *, retained_evidence=()):
    """Keep page/reference pairs together; original text is restored downstream.

    Unnumbered legacy contexts retain their existing literal validation. A page
    whose individual lines exceed capacity also retains literal-substring
    transport; it must not disappear merely because a reference cannot fit.
    """
    pages = {}
    for message in messages:
        content = message.get('content', '')
        if not isinstance(content, str) or not content.startswith('<UNTRUSTED_DOCUMENT_CONTENT>\n'):
            continue
        try:
            payload = json.loads(content.split('\n', 1)[1].rsplit('\n', 1)[0])
            for page in payload.get('source_pages', []):
                if 'evidence_reference_options' in page:
                    pages[page['page']] = page
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
    if not pages:
        return base
    variants = {}
    for number, page in sorted(pages.items()):
        fields = dict(page=(Literal[number], ...))
        refs = tuple(option['ref'] for option in page['evidence_reference_options'])
        existing = tuple(q.text for q in retained_evidence if q.page == number)
        fields['text'] = (_page_reference_type(page, refs, existing), ...)
        variants[number] = create_model(f'SourcePage{number}Reference', __base__=BriefQuote, **fields)
    quotation = next(iter(variants.values())) if len(variants) == 1 else Union[tuple(variants.values())]
    if retained_evidence and len(variants) > 1:
        def select_page(value):
            # A known page has only one possible schema. Report its own field
            # error rather than unrelated alternatives from every other page.
            raw = value.model_dump() if isinstance(value, BaseModel) else value
            if isinstance(raw, dict) and type(raw.get('page')) is int and raw['page'] in variants:
                return variants[raw['page']].model_validate(raw)
            return value

        quotation = Annotated[quotation, BeforeValidator(select_page)]

    def plain_value(value):
        return value.model_dump(mode='json') if isinstance(value, BaseModel) else value

    return create_model(base.__name__, __base__=base,
        __validators__={'plain_reference_value': model_validator(mode='before')(plain_value)},
        evidence=(list[quotation], deepcopy(base.model_fields['evidence'])))


def source_draft_schema(messages, base):
    from .source_table_cells import source_cell_item_schema
    from .source_integration_review import SourceDisposition
    decision = referenced_evidence_model(messages, SourceDisposition)
    addition = referenced_evidence_model(messages, source_cell_item_schema(messages))
    return create_model(base.__name__, __base__=base,
        decisions=(list[decision], deepcopy(base.model_fields['decisions'])),
        additions=(list[addition], deepcopy(base.model_fields['additions'])))
