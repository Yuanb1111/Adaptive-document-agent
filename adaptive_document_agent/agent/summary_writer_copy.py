"""Writer-owned meaning addresses, mechanically bound to exact current copy."""
from copy import deepcopy
from functools import lru_cache
from types import UnionType
from typing import Union, get_args, get_origin

from pydantic import BaseModel, ConfigDict, Field, create_model


class SummaryWriterMeaningRef(BaseModel):
    model_config = ConfigDict(extra='forbid')
    part_id: str
    meaning_index: int = Field(ge=0)


def _writer_annotation(annotation):
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return writer_schema(annotation)
    origin, arguments = get_origin(annotation), get_args(annotation)
    if origin is list:
        return list[_writer_annotation(arguments[0])]
    if origin in (Union, UnionType):
        mapped = tuple(_writer_annotation(argument) for argument in arguments)
        return Union[mapped] if mapped != arguments else annotation
    return annotation


@lru_cache(maxsize=128)
def writer_schema(schema):
    """Clone only affected schema paths; preserve operation names and all constraints."""
    fields = {}
    for name, field in schema.model_fields.items():
        if name == 'meaning_refs' and 'text' in schema.model_fields:
            annotation = list[SummaryWriterMeaningRef]
            copied = deepcopy(field)
            copied.description = ('Identify only exact source part_id and meaning_index for meanings '
                'expressed in this current paragraph. Python binds its full exact text; these '
                'addresses do not establish semantic coverage or approval.')
        else:
            annotation = _writer_annotation(field.annotation)
            copied = deepcopy(field)
        if annotation != field.annotation:
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
