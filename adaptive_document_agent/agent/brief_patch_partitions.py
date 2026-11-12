"""Bounded independent item patches, followed by the unchanged whole-brief gates."""
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from copy import deepcopy
import json

from pydantic import ConfigDict, create_model

from adaptive_document_agent.services.llm.base import LLMResponse
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
from .brief_patch_capacity import compact_overlong_patch, complete_patch
from .prompting import untrusted_document_message


def generate_patch(gateway, messages, schema, context, audit, *, cancelled=None):
    """Give a complex patch one request per editable item, never an extra loop.

    Serial/local clients retain the existing single-request transport. Every
    request still uses LLMGateway and its privacy, concurrency and usage limits.
    Returned fields are only candidates; source, locks, coverage and independent
    whole-brief review remain with the caller.
    """
    item_keys = [key for key in schema.model_fields if key.startswith('item_')]
    workers = getattr(gateway, 'discovery_workers', 1)
    reference_items = set(context.get('source_quantity_reference_options', {})) & set(item_keys)
    mixed_transport = bool(reference_items) and reference_items != set(item_keys)
    if (len(item_keys) < 3 and not mixed_transport) or workers < 2:
        try:
            return gateway.generate_structured(messages, schema, stage='report',
                allow_repair=False, max_tokens=12000, cancelled=cancelled)
        except LLMStructuredOutputError as error:
            return compact_overlong_patch(gateway, messages, schema, error,
                audit.setdefault('patch_capacity', {}), cancelled=cancelled)
    common = [key for key in schema.model_fields if key not in item_keys]
    records = audit['patch_partitions'] = [{} for _ in item_keys]

    def request(position, key):
        keys = [key, *common] if position == 0 else [key]
        part_schema = create_model(schema.__name__, __config__=ConfigDict(extra='forbid'),
            **{name: (schema.model_fields[name].annotation, deepcopy(schema.model_fields[name]))
               for name in keys})
        scoped = deepcopy(context)
        siblings = scoped.get('invalid_items', {})
        scoped['parallel_sibling_drafts'] = {name: {field: value.get(field) for field in ('label', 'text')}
            for name, value in siblings.items() if name not in keys}
        for field in ('invalid_items', 'source_native_money_options', 'source_quantity_reference_options',
                      'source_qualification_options', 'validation_errors'):
            if isinstance(scoped.get(field), dict):
                scoped[field] = {name: value for name, value in scoped[field].items()
                                 if name in keys or not name.startswith('item_')}
        record = records[position]
        record['requested_fields'] = keys
        part_messages = [*messages[:-1], untrusted_document_message(json.dumps(scoped, ensure_ascii=False)),
            dict(role='user', content='This is one independent partition of the SAME bounded patch. '
                 'Return only these exact fields: ' + ', '.join(keys) + '. '
                 + ('Use the item-owned quantity reference array from this partition only. '
                    if key in reference_items else
                    'This item has NO quantity reference transport: text MUST be a literal STRING; '
                    'never return an array or borrow reference IDs from another item. ') +
                 'Resolve every listed error for this item using the complete original source context. '
                 'Other parallel_sibling_drafts are unverified context, not facts or editable fields. '
                 'Do not depend on a sibling to carry this item’s required qualification. '
                 'The body limit counts CHARACTERS, including spaces and punctuation, not words. '
                 'Aim below the supplied limit and omit secondary figures. '
                 'The merged brief still needs fresh whole-brief review.')]
        try:
            try:
                value = gateway.generate_structured(part_messages, part_schema, stage='report',
                    allow_repair=False, max_tokens=12000, cancelled=cancelled)
            except LLMStructuredOutputError as error:
                value = compact_overlong_patch(gateway, part_messages, part_schema, error, record,
                                               cancelled=cancelled)
            value = part_schema.model_validate(value.model_dump()).model_dump(mode='json')
            record['response'] = value
            return value
        except Exception as exc:
            record['error'] = str(exc)
            raise

    with ThreadPoolExecutor(max_workers=min(workers, len(item_keys)), thread_name_prefix='brief-patch') as pool:
        futures = [pool.submit(copy_context().run, request, position, key)
                   for position, key in enumerate(item_keys)]
        # Wait for every authorized request before returning or surfacing a
        # failure; no unobserved background requests survive the stage.
    combined, failures = {}, []
    for position, future in enumerate(futures):
        try:
            combined.update(future.result())
        except Exception as error:
            failures.append(error)
            if isinstance(error, LLMStructuredOutputError):
                try:
                    combined.update(complete_patch(error, records[position]['requested_fields']))
                except (ValueError, TypeError, LLMStructuredOutputError):
                    pass
    if failures:
        # Preserve complete successful siblings in the caller's existing strict
        # partial-item recovery; this envelope grants no semantic acceptance.
        if (all(isinstance(error, LLMStructuredOutputError) for error in failures)
                and set(combined) == set(schema.model_fields)):
            raise LLMStructuredOutputError('One or more item patches failed schema validation',
                response=LLMResponse(text=json.dumps(combined, ensure_ascii=False))) from failures[0]
        raise failures[0]
    return schema.model_validate(combined)
