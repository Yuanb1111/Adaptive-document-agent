"""Request-local navigation references, resolved exactly to retained source IDs."""
from collections import Counter
from copy import deepcopy


REFERENCE_INSTRUCTIONS = (
    'Use the short target IDs from targets[].id in each range observation_ids, and the short '
    'section IDs from sections[].id in section_id. Copy these IDs exactly; numeric indices '
    'in raw-value navigation hits refer to targets[].index. Never reconstruct a persistent '
    'observation ID from memory. Each range must list unique target IDs. The same target may '
    'need multiple ranges. References locate data only and do not establish assurance. ')


class AuditDiscoveryReferenceError(ValueError):
    """Exact field failures and allowed references for one bounded correction."""
    def __init__(self, issues):
        self.issues = issues
        super().__init__('; '.join(f"{i['field']}: {i['message']}" for i in issues))


def _references(ids, prefix):
    ids = list(ids)
    if len(ids) != len(set(ids)):
        raise ValueError('Audit discovery input contains duplicate retained identities.')
    reserved = set(ids)
    result = {}
    number = 0
    for source_id in ids:
        while f'{prefix}{number}' in reserved:
            number += 1
        result[f'{prefix}{number}'] = source_id
        number += 1
    return result


def reference_input(payload):
    """Preserve every target, source and index; substitute only opaque addresses."""
    targets = _references((o['id'] for o in payload['targets']), 't')
    sections = _references((s['id'] for s in payload['sections']), 's')
    reverse_targets = {value: key for key, value in targets.items()}
    reverse_sections = {value: key for key, value in sections.items()}
    wire = deepcopy(payload)
    for target in wire['targets']:
        target['id'] = reverse_targets[target['id']]
    for section in wire['sections']:
        section['id'] = reverse_sections[section['id']]
    for check in wire['source_checks']:
        check['section_id'] = reverse_sections.get(check['section_id'], check['section_id'])
    return wire, dict(targets=targets, sections=sections)


def resolve_selection(selection, references):
    """No fuzzy matching, dropped IDs, semantic substitutions or automatic approval."""
    targets, sections = references['targets'], references['sections']
    # Exact canonical IDs remain readable for previously saved/controlled replies.
    # Short aliases are disjoint from them, so a token never has two meanings.
    targets = {**{value: value for value in targets.values()}, **targets}
    sections = {**{value: value for value in sections.values()}, **sections}
    resolved = selection.model_copy(deep=True)
    issues = []
    for index, span in enumerate(resolved.ranges):
        if span.section_id not in sections:
            issues.append(dict(field=f'ranges[{index}].section_id',
                message='Unknown indexed section reference.', received=span.section_id,
                allowed_references=list(references['sections'])))
        else:
            span.section_id = sections[span.section_id]
        unknown = [oid for oid in span.observation_ids if oid not in targets]
        mapped = [targets[oid] for oid in span.observation_ids if oid in targets]
        duplicates = [oid for oid, count in Counter(mapped).items() if count > 1]
        if unknown or duplicates:
            issues.append(dict(field=f'ranges[{index}].observation_ids',
                message='Duplicated or unknown observation references.',
                unknown_references=unknown, duplicate_observation_ids=duplicates,
                allowed_references=list(references['targets'])))
        else:
            span.observation_ids = mapped
    if issues:
        raise AuditDiscoveryReferenceError(issues)
    return resolved
