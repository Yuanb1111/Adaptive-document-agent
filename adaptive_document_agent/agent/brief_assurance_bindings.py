"""Model-selected assurance scopes, checked against exact owned source columns."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class BriefAssuranceBinding(BaseModel):
    model_config = ConfigDict(extra='forbid')
    claim: str = Field(min_length=1, max_length=550,
        description='Exact contiguous body clause identifying the qualified measure, period and status.')
    status: Literal['audited', 'unaudited']
    source_refs: list[str] = Field(min_length=1, max_length=40,
        description='Exact assurance catalogue IDs for ALL measures qualified by this clause.')


def assurance_catalog(inventory: list[dict]) -> dict[str, dict]:
    """Keep row/column ownership; unknown is an explicit non-authorizing entry."""
    catalog = {}
    for table in inventory:
        for column in table['columns']:
            catalog[f'a{len(catalog)}'] = dict(page=table['page'], table_id=table['table_id'],
                row_labels=list(table['row_labels']), **{key: column[key] for key in
                    ('column', 'period', 'status', 'date_aliases', 'column_label') if key in column})
    return catalog


def assurance_binding_errors(item, inventory, bindings):
    """A model's status declaration must actually appear in its audience span.

    This validates the declared transport, not the semantic measure ownership.
    Missing scope may use the existing contract retry only when its selected
    source columns support the status. Unknown or unrelated columns never do.
    """
    import re
    from .brief_audit_scope import _PERIOD, _STATUS, _period_keys
    catalog = assurance_catalog(inventory)
    errors, recoverable = [], True
    for number, value in enumerate(bindings or []):
        prefix = f'Assurance binding {number}: '
        try:
            binding = BriefAssuranceBinding.model_validate(value)
        except ValueError:
            errors.append(prefix + 'invalid source binding')
            recoverable = False
            continue
        refs = binding.source_refs
        if (len(refs) != len(set(refs)) or any(ref not in catalog for ref in refs)
                or any(catalog[ref]['status'] != binding.status for ref in refs)):
            errors.append(prefix + 'references do not support the declared status')
            recoverable = False
            continue
        if item.text.count(binding.claim) != 1:
            errors.append(prefix + 'claim must be one exact unique audience clause')
            continue
        sources = [catalog[ref] for ref in refs]
        periods = {key for match in _PERIOD.finditer(binding.claim)
                   for key in _period_keys(match, sources)}
        if not any(match[0].casefold() == binding.status for match in _STATUS.finditer(binding.claim)):
            errors.append(prefix + 'declared status is missing from its audience clause')
        if any(re.sub(r'\s+', '', source['period']).upper() not in periods for source in sources):
            errors.append(prefix + 'source period is missing from its audience clause')
    return errors, bool(errors) and recoverable


def bound_assertion(item, status, period, keys, inventory, bindings) -> bool:
    """Validate a semantic scope choice without guessing a measure from prose.

    The independent meaning reviewer owns the clause-to-measure association.
    Python requires a unique literal audience span and its exact owned source
    row/column, period and status. A known status elsewhere cannot lend a label
    to an unknown source reference. This alone never approves the finding.
    """
    import re
    if not bindings:
        return False
    catalog = assurance_catalog(inventory)
    for binding in bindings or []:
        try:
            binding = BriefAssuranceBinding.model_validate(binding)
        except ValueError:
            continue
        if binding.status != status[0].casefold() or item.text.count(binding.claim) != 1:
            continue
        start = item.text.index(binding.claim)
        stop = start + len(binding.claim)
        if not (start <= min(status.start(), period.start())
                and max(status.end(), period.end()) <= stop):
            continue
        refs = binding.source_refs
        if len(refs) != len(set(refs)) or any(ref not in catalog for ref in refs):
            continue
        sources = [catalog[ref] for ref in refs]
        if all(source['status'] == binding.status
               and re.sub(r'\s+', '', source['period']).upper() in keys for source in sources):
            return True
    return False
