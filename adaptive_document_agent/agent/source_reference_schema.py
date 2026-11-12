"""Transport source quotations as measured references rather than transcriptions."""
from copy import deepcopy
import json
from typing import Literal, Union

from pydantic import BaseModel, create_model, model_validator

from adaptive_document_agent.models.executive_brief import BriefQuote


def referenced_evidence_model(messages, base):
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
                    pages[page['page']] = tuple(option['ref'] for option in page['evidence_reference_options'])
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
    if not pages:
        return base
    variants = []
    for number, refs in sorted(pages.items()):
        fields = dict(page=(Literal[number], ...))
        if refs:
            fields['text'] = (Literal[refs], ...)
        variants.append(create_model(f'SourcePage{number}Reference', __base__=BriefQuote, **fields))
    quotation = variants[0] if len(variants) == 1 else Union[tuple(variants)]

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
