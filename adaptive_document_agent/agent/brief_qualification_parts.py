"""Fit complete source-owned brief clauses without truncating model-authored text."""
import json
from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model, model_validator

from adaptive_document_agent.models.executive_brief import ExecutiveBriefItem
from .brief_assurance_bindings import BriefAssuranceBinding
from .brief_reviewed_qualifications import narrower_qualification_options, qualification_quantity_errors

BODY_LIMIT = ExecutiveBriefItem.model_json_schema()['properties']['text']['maxLength']


class AuthoredPart(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    text: str = Field(min_length=1, max_length=BODY_LIMIT)
    assurance_bindings: list[BriefAssuranceBinding] = Field(default_factory=list, max_length=20)

    @model_validator(mode='after')
    def local_assurance(self):
        if any(self.text.count(b.claim) != 1 for b in self.assurance_bindings):
            raise ValueError('Each assurance binding must quote one exact clause in this alternative.')
        return self


def qualification_parts(brief, continuation):
    parts, options = {}, {}
    for i, aliases in continuation['quote_alias_options'].items():
        previous = continuation['previous_bindings'][i]
        refs = list(dict.fromkeys(b['source_ref'] for b in previous))
        owned = narrower_qualification_options(refs, continuation['previous_options'][i], aliases)
        options[i] = owned
        finding = brief.items[i].text
        for binding in previous:
            if binding['source_ref'] in owned:
                finding = finding.replace(binding['claim'], ' ', 1)
        finding = ' '.join(finding.split())
        slots = {'finding': dict(current_text=finding, source_ref=None)} if finding else {}
        for n, ref in enumerate(owned, 1):
            current = ' '.join(b['claim'] for b in previous if b['source_ref'] == ref)
            slots[f'qualification_{n}'] = dict(current_text=current, source_ref=ref)
        # Split between the current distribution and equal shares so a newly
        # requested qualification also receives space. Reserve actual joiners.
        available = BODY_LIMIT - len(slots) + 1
        weight = sum(len(s['current_text']) for s in slots.values())
        for s in slots.values():
            length = len(s['current_text'])
            s['compact_max_characters'] = (available // len(slots) if not weight else
                available * (weight + length * len(slots)) // (2 * weight * len(slots)))
        slack = available - sum(s['compact_max_characters'] for s in slots.values())
        for s in list(slots.values())[:slack]:
            s['compact_max_characters'] += 1
        for s in slots.values():
            s['compact_target_characters'] = 3 * s['compact_max_characters'] // 4
        parts[i] = slots
    return parts, options


def part_item_model(index, slots, *, pooled=False):
    fields = {'label': (str | None, Field(default=None, min_length=1, max_length=60))}
    for key, slot in slots.items():
        cap = BODY_LIMIT if pooled else slot['compact_max_characters']
        compact = create_model(f'Compact_{index}_{key}', __base__=AuthoredPart,
            text=(str, Field(min_length=1, max_length=cap)))
        alternatives = create_model(f'Alternatives_{index}_{key}', __config__=ConfigDict(extra='forbid'),
            concise=(AuthoredPart, ...), compact=(compact, ...))
        fields[key] = (alternatives, ...)
    return create_model(f'QualifiedBriefParts_{index}', __config__=ConfigDict(extra='forbid'), **fields)


def repack_oversized_compacts(raw, schema, parts, options, editable, *, preserved_findings=None):
    """Use already authored whole alternatives if only per-part allocation overflowed."""
    try:
        data = json.loads(raw)
        schema.model_validate(data)
    except ValidationError as exc:
        for error in exc.errors():
            loc = error['loc']
            if (error['type'] != 'string_too_long' or len(loc) != 4
                    or loc[-2:] != ('compact', 'text')):
                return None
    except (ValueError, TypeError):
        return None
    else:
        return None
    relaxed = create_model('ExistingQualificationAlternatives', __config__=ConfigDict(extra='forbid'),
        **{f'item_{i}':(part_item_model(i, parts[i], pooled=True), ...) for i in editable})
    try:
        candidate = relaxed.model_validate(data)
        for i in editable:
            assemble_parts(getattr(candidate, f'item_{i}').model_dump(mode='json'), parts[i], options[i],
                           preserved_finding=(preserved_findings or {}).get(i))
    except ValueError:
        return None
    return candidate


def assemble_parts(value, slots, options, *, preserved_finding=None):
    """Prefer the model's first alternative wherever the entire brief item fits."""
    choices = {}
    for key, slot in slots.items():
        ref = slot['source_ref']
        alternatives = [value[key][name] for name in ('concise', 'compact')]
        if key == 'finding' and preserved_finding and preserved_finding['text'] == slot['current_text']:
            # This unchanged model-authored part predates the newly targeted
            # source qualification. Prefer it when it fits; the assembled item
            # and all siblings still undergo complete independent review.
            alternatives.insert(0, preserved_finding)
        valid = [part for part in alternatives if not ref or
                 not qualification_quantity_errors(part['text'], ref, options)]
        if not valid:
            raise ValueError(f'{key}: neither authored alternative binds its quantities to {ref}.')
        choices[key] = valid
    selected = {key:min(parts, key=lambda p:len(p['text'])) for key,parts in choices.items()}
    length = sum(len(p['text']) for p in selected.values()) + len(selected) - 1
    if length > BODY_LIMIT:
        raise ValueError('The source-valid complete alternatives exceed the brief item limit.')
    for key, alternatives in choices.items():
        extra = len(alternatives[0]['text']) - len(selected[key]['text'])
        if length + extra <= BODY_LIMIT:
            selected[key] = alternatives[0]
            length += extra
    return dict(text=' '.join(part['text'] for part in selected.values()), label=value['label'],
                assurance_bindings=[b for p in selected.values() for b in p['assurance_bindings']],
                source_qualifications=[dict(claim=selected[key]['text'], source_ref=slot['source_ref'])
                                       for key,slot in slots.items() if slot['source_ref']])
