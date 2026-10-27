"""Exact item-owned amount references for a bounded numeric patch, never rounding."""
from copy import deepcopy

from pydantic import BaseModel, ConfigDict, Field, create_model

from adaptive_document_agent.services.executive_brief import _quantities
from .brief_evidence_blocks import ReferencedBriefItem


class NativeQuantityReference(BaseModel):
    model_config = ConfigDict(extra='forbid')
    quantity_ref: str = Field(min_length=1, max_length=30)


NativeQuantityBriefItem = create_model('NativeQuantityBriefItem', __base__=ReferencedBriefItem,
    text=(list[str | NativeQuantityReference] | str, Field(
        description='Use prose/reference segments for exact native quantity repairs. Legacy literal text remains subject to all unchanged source checks.')))


def quantity_patch_fields(fields, native_options, errors):
    """Keep original source quantities scoped to their own failing finding."""
    fields, catalogs = dict(fields), {}
    for key, options in native_options.items():
        if key not in fields or not any(any(marker in error for marker in (
                'amount changes a source currency or magnitude', 'magnitude representation',
                'unsupported numeric claims')) for error in errors.get(key, [])):
            continue
        catalog = {}
        for option in options:
            bases = option.get('literal_basis', [''])
            if len(bases) != 1:
                continue  # An ambiguous denominator has no automatically chosen spelling.
            amount = option['amount_text'] + (' per ' + bases[0] if bases[0] else '')
            if amount not in catalog.values():
                catalog[f'q{len(catalog)}'] = amount
        if catalog:
            fields[key] = (NativeQuantityBriefItem, ...)
            catalogs[key] = catalog
    return fields, catalogs


def expand_quantity_patch(values, catalogs):
    """Join model-written prose with exact chosen strings; all normal gates follow."""
    result = deepcopy(values)
    for key, catalog in catalogs.items():
        if key not in result or not isinstance(result[key], dict):
            continue  # The immutable patch schema reports missing/invalid keys.
        parts = result[key].get('text')
        if isinstance(parts, str):
            # Compatible literal replies get no rewriting or additional trust.
            # Their exact numbers, scale, sign and meaning still face every gate.
            continue
        if not isinstance(parts, list) or not 1 <= len(parts) <= 40:
            raise ValueError('Native quantity patch text requires explicit prose/reference segments.')
        if result[key].get('quantity_representations'):
            raise ValueError('Signed native quantity references must not carry positive-magnitude annotations.')
        rendered, plain = [], ''
        for part in parts:
            if isinstance(part, str):
                plain += part
                continue
            if any(currency for currency, _, _ in _quantities(plain)):
                raise ValueError('Monetary amounts in a native quantity patch must use owned quantity references.')
            rendered.append(plain)
            plain = ''
            if (not isinstance(part, dict) or set(part) != {'quantity_ref'}
                    or not isinstance(part['quantity_ref'], str) or part['quantity_ref'] not in catalog):
                raise ValueError('Unknown item-owned native quantity reference.')
            rendered.append(catalog[part['quantity_ref']])
        if any(currency for currency, _, _ in _quantities(plain)):
            raise ValueError('Monetary amounts in a native quantity patch must use owned quantity references.')
        rendered.append(plain)
        result[key]['text'] = ''.join(rendered)
    return result


QUANTITY_REFERENCE_INSTRUCTIONS = (
    'For item_N fields with source_quantity_reference_options, text is an ARRAY of alternating '
    'prose strings and {"quantity_ref":"qN"} objects, not one prose string. Select exact IDs '
    'from that item\'s own options for EVERY monetary amount. Python inserts the chosen signed '
    'amount verbatim; you must not write currency amounts in prose segments, round, rescale or '
    'choose a nearby value. Write connecting prose, periods and qualifications around the references. '
    'These quantities preserve source sign, scale and denominator. Use an empty '
    'quantity_representations list because these are exact signed values, not positive magnitude '
    'substitutions. A loss remains explicitly negative. The combined text must still fit 550 '
    'characters. All evidence, source semantics and independent meaning checks still apply. ')
