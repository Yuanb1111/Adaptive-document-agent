"""Limit a settled selection's copy recheck to the pages actually revised."""


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
        'proposed_selection': {**selection, 'decisions': decisions,
            'ordered_insight_ids': [iid for iid in selection['ordered_insight_ids'] if iid in targets]},
        'settled_selection_ids': selection['ordered_insight_ids'],
        # Qualitative qualifications can belong to a related measure. Never
        # trim these original pages to just the target's numeric row locations.
        'source_pages': payload.get('source_pages', []),
    }
