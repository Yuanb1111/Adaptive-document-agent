"""Writer-owned meaning addresses, mechanically bound to exact current copy."""
from copy import deepcopy
from functools import lru_cache
from types import UnionType
from typing import Union, get_args, get_origin

from pydantic import BaseModel, ConfigDict, Field, create_model
from pydantic_core import PydanticUndefined


class SummaryWriterMeaningRef(BaseModel):
    model_config = ConfigDict(extra='forbid')
    part_id: str
    meaning_index: int = Field(ge=0)


def _writer_annotation(annotation, require_display):
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return writer_schema(annotation, require_display=require_display)
    origin, arguments = get_origin(annotation), get_args(annotation)
    if origin is list:
        return list[_writer_annotation(arguments[0], require_display)]
    if origin in (Union, UnionType):
        mapped = tuple(_writer_annotation(argument, require_display) for argument in arguments)
        return Union[mapped] if mapped != arguments else annotation
    return annotation


@lru_cache(maxsize=128)
def writer_schema(schema, *, require_display=None):
    """Clone only affected schema paths; preserve operation names and all constraints."""
    if require_display is None:
        require_display = any(base.__name__ == 'SummarySynthesisDraft' for base in schema.__mro__)
    fields = {}
    for name, field in schema.model_fields.items():
        if name == 'meaning_refs' and 'text' in schema.model_fields:
            annotation = list[SummaryWriterMeaningRef]
            copied = deepcopy(field)
            copied.description = ('Identify only exact source part_id and meaning_index for meanings '
                'expressed in this current paragraph. Python binds its full exact text; these '
                'addresses do not establish semantic coverage or approval.')
        elif require_display and name == 'display' and 'text' in schema.model_fields:
            from adaptive_document_agent.models.summary_display import SummaryDisplay
            annotation = writer_schema(SummaryDisplay, require_display=True)
            copied = Field(description='Choose an explicit supported display layout for this complete item. '
                'Use paragraphs when no source-supported semantic visual structure is appropriate.')
        else:
            annotation = _writer_annotation(field.annotation, require_display)
            copied = deepcopy(field)
        if require_display and schema.__name__ == 'SummaryDisplay' and name == 'layout':
            copied.default = PydanticUndefined
            copied.default_factory = None
        if annotation != field.annotation or copied.is_required() != field.is_required():
            fields[name] = (annotation, copied)
    if not fields:
        return schema
    return create_model(schema.__name__, __base__=schema, **fields)


def bind_writer_copy(value, schema):
    """Never choose a mapping: bind each supplied address to its own current paragraph."""
    data = value.model_dump(mode='json')
    count = 0
    def bind(node):
        nonlocal count
        if isinstance(node, dict):
            if isinstance(node.get('text'), str) and isinstance(node.get('meaning_refs'), list):
                for reference in node['meaning_refs']:
                    reference['summary_quote'] = node['text']
                    count += 1
            for child in node.values():
                bind(child)
        elif isinstance(node, list):
            for child in node:
                bind(child)
    bind(data)
    return schema.model_validate(data), count


def address_only_copy(data):
    """A serialization view for retained writer copy; never change claims or addresses."""
    value = deepcopy(data)
    def strip(node):
        if isinstance(node, dict):
            if isinstance(node.get('text'), str) and isinstance(node.get('meaning_refs'), list):
                for reference in node['meaning_refs']:
                    reference.pop('summary_quote', None)
            for child in node.values():
                strip(child)
        elif isinstance(node, list):
            for child in node:
                strip(child)
    strip(value)
    return value
