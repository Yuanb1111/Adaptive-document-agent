"""Presentation of independently reviewed assurance, bound to individual measures."""
import re


def pure_audit_caveat(text):
    """Only replace standalone assurance clauses; preserve unrelated limitations."""
    clauses = re.split(r'[;.]+\s*', text.strip().rstrip('.'))
    period = r'(?:FY\d{4}|\d{1,2}M\d{4}|\d{4}-\d{2}-\d{2})'
    return bool(clauses) and all(re.fullmatch(
        rf'{period}(?:\s+(?:is|are))?\s+(?:unaudited|audited)|'
        rf'{period}\s+audit status (?:is )?unknown', part.strip(), re.I)
        for part in clauses if part.strip())


def report_audit_scope_notes(result, observations):
    """Do not let an audited amount imply assurance of a neighboring ratio."""
    from adaptive_document_agent.agent.report_audit_scope import reviewed_audit_bindings
    from .presentation_labels import qualified_metric_name
    bindings = reviewed_audit_bindings(result)
    if not any(o.id in bindings for o in observations):
        return []
    groups = {}
    for observation in observations:
        binding = bindings.get(observation.id)
        status = binding.status if binding else observation.audited_status
        period = observation.period or ''
        key = (period, status)
        groups.setdefault(key, []).append(observation)
    notes = []
    for (period, status), measures in sorted(groups.items()):
        names = list(dict.fromkeys(qualified_metric_name(o) for o in measures))
        if status in {'audited', 'unaudited'}:
            evidence = [q.page for o in measures if o.id in bindings
                        for q in [bindings[o.id].value_quote, *bindings[o.id].scope_evidence]]
            source = ' (source pp. ' + ', '.join(map(str, sorted(set(evidence)))) + ')' if evidence else ''
            notes.append(f"{period} {', '.join(names)}: {status}{source}.")
        else:
            notes.append(f"{period} {', '.join(names)}: audit status is not established for these measures.")
    return notes


def bind_brief_audit_inventory(inventory, result):
    """Resolve a specific source row/column only; adjacent percentages stay unknown."""
    from adaptive_document_agent.agent.report_audit_scope import reviewed_audit_bindings
    bindings = reviewed_audit_bindings(result)
    if not bindings:
        return inventory
    by_id = {o.id: o for o in result.observations}
    expanded = []
    for table in inventory:
        for label in table['row_labels']:
            matched = [(by_id[oid], binding) for oid, binding in bindings.items()
                       if oid in by_id and by_id[oid].effective_table_id == table['table_id']
                       and any(e.page == table['page'] and (e.row_label or '').casefold() == label.casefold()
                               for e in by_id[oid].evidence)]
            if not matched:
                expanded.append({**table, 'row_labels': [label]})
                continue
            columns = []
            for column in table['columns']:
                linked = [binding for observation, binding in matched
                          if observation.column_id == column['column'] and observation.period == column['period']]
                if len(linked) == 1 and column['status'] == 'unknown':
                    columns.append({**column, 'status': linked[0].status,
                        'report_assurance_evidence': [q.model_dump(mode='json') for q in linked[0].scope_evidence],
                        'report_assurance_observation_id': linked[0].observation_id})
                else:
                    columns.append(dict(column))
            expanded.append({**table, 'row_labels': [label], 'columns': columns,
                             'binding_basis': 'quoted_source_grid_and_independently_reviewed_exact_measure'})
    return expanded
