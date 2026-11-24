"""Limit a settled selection's copy recheck to the pages actually revised."""


MAX_COPY_REVIEW_REASON_CHARACTERS = 4000


def source_first_wire_payload(payload: dict) -> dict:
    """Put shared complete source pages before owner-specific fields for prefix reuse."""
    if 'source_pages' not in payload:
        return payload
    return {'source_pages': payload['source_pages'],
            **{key: value for key, value in payload.items() if key != 'source_pages'}}


def copy_review_payload(payload: dict) -> dict:
    """Scope structured inputs, keeping all supplied original source context.

    The full selection remains available to deterministic verdict validation and
    the later publication gate. This packet cannot grant an omission verdict.
    """
    targets = set(payload.get('copy_review_ids', ()))
    if not targets:
        return payload
    findings = [f for f in payload['findings'] if f['insight']['id'] in targets]
    if {f['insight']['id'] for f in findings} != targets:
        raise ValueError('Copy review requires exact current finding IDs')
    selection = payload['proposed_selection']
    decisions = [d for d in selection['decisions'] if d['insight_id'] in targets
                 and d['decision'] == 'include']
    if {d['insight_id'] for d in decisions} != targets:
        raise ValueError('Copy review can only check included pages')
    audience_decisions, retained_proofs = [], {}
    for decision in decisions:
        if not (page := decision.get('page')):
            audience_decisions.append(decision)
            continue
        visible_context, context_proofs = [], []
        for item in page.get('source_context', []):
            visible_context.append({key: item[key] for key in ('scope', 'description')})
            context_proofs.append({key: value for key, value in item.items()
                                   if key not in ('scope', 'description')})
        retained_proofs[decision['insight_id']] = dict(
            context_evidence=page.get('context_evidence', []), source_context=context_proofs)
        audience_page = {key: value for key, value in page.items()
                         if key not in ('source_context', 'context_evidence')}
        if visible_context:
            audience_page['source_context'] = visible_context
        audience_decisions.append({**decision, 'page': audience_page})
    citations = [c for c in payload['planned_source_citations'] if c['insight_id'] in targets]
    ids = {oid for f in findings for oid in f['observation_ids']}
    ids.update(oid for c in citations for oid in c['observation_ids'])
    tasks = {tid for f in findings for tid in f['insight'].get('result_ids', [])}
    calculations = [c for c in payload.get('calculations', []) if c['task_id'] in tasks]
    ids.update(oid for c in calculations for oid in c['input_observation_ids'])
    tables = {r['table_id'] for r in payload.get('source_rows', [])
              if r['id'] in ids and r['table_id'] is not None}
    rows = [r for r in payload.get('source_rows', []) if r['id'] in ids or r['table_id'] in tables]
    row_ids = ids | {r['id'] for r in rows}
    available_pages = {p['page'] for p in payload.get('source_pages', [])}
    anchors = {page for citation in citations for page in citation.get('source_pages', [])}
    anchors.update(evidence.get('page') for observation in payload.get('observations', [])
                   if observation.get('id') in row_ids
                   for evidence in observation.get('evidence', [])
                   if isinstance(evidence.get('page'), int))
    source_reading_pages = sorted({page + offset for page in anchors for offset in range(-2, 3)
                                   if page + offset in available_pages})
    return {
        **payload,
        'findings': findings,
        'unavailable_findings': [],
        'analysis_plan': [a for a in payload.get('analysis_plan', []) if a['id'] in tasks],
        'calculations': calculations,
        'bound_calculations':[c for c in payload.get('bound_calculations',[])
                              if set(c['observation_ids'])<=row_ids],
        'observations': [o for o in payload.get('observations', []) if o['id'] in row_ids],
        'source_rows': rows,
        'source_row_assurance': {k: v for k, v in payload['source_row_assurance'].items() if k in row_ids},
        'verified_column_assurance': {k: v for k, v in payload['verified_column_assurance'].items() if k in row_ids},
        'planned_source_citations': citations,
        # Help a focused reviewer re-read the owning evidence and adjacent
        # discussion without removing any other original source page.
        'source_reading_pages': source_reading_pages,
        'proposed_selection': {**selection, 'decisions': audience_decisions,
            'ordered_insight_ids': [iid for iid in selection['ordered_insight_ids'] if iid in targets]},
        'retained_proofs': retained_proofs,
        'settled_selection_ids': selection['ordered_insight_ids'],
        # Qualitative qualifications can belong to a related measure. Never
        # trim these original pages to just the target's numeric row locations.
        'source_pages': payload.get('source_pages', []),
    }
