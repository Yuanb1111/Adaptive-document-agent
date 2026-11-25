"""Limit a settled selection's copy recheck to the pages actually revised."""


MAX_COPY_REVIEW_REASON_CHARACTERS = 4000


def changed_description_slots(previous, current):
    """Identify current slots where the audience scope or description changed after an owner rejection."""
    before = [(item.scope, item.description) for item in previous.source_context]
    return [f'context-{i}' for i, item in enumerate(current.source_context)
            if i >= len(before) or (item.scope, item.description) != before[i]]


def published_description_changes(changes, context, selection, result):
    from .retained_analysis import findings
    from .retained_page_sources import page_bindings

    current = {}
    linked = findings(result, allow_new_copy=True)
    for decision in selection.decisions:
        owner = decision.insight_id
        slots = changes.get(owner)
        if not slots or owner not in context['copy_review_ids'] or decision.decision != 'include':
            continue
        insight, primary, _ = linked[owner]
        rendered = {}
        page_bindings(decision.page, insight, primary, context, result, rendered_descriptions=rendered)
        if set(slots) - rendered.keys():
            raise ValueError('A changed description must identify a current reader-facing source slot.')
        current[owner] = {slot: dict(audience_text=rendered[slot],
            source_pages=sorted({q.page for q in item.proof_quotes}))
            for i,item in enumerate(decision.page.source_context) if (slot := f'context-{i}') in slots}
    return current


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
    changes = {iid: slots for iid, slots in payload.get('revised_source_descriptions', {}).items()
               if iid in targets and slots}
    if 'revised_source_descriptions' in payload:
        payload = {key: value for key, value in payload.items() if key != 'revised_source_descriptions'}
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
        audience_decisions.append(dict(insight_id=decision['insight_id'], decision=decision['decision'],
                                       page=audience_page))
    # Once a page has been authored, provisional finding prose and objections
    # to older drafts can contradict the copy under review. They stay in the
    # selection/repair history. Keep the source and calculation links here.
    evidence_fields = ('id', 'kind', 'metric', 'result_ids', 'evidence', 'driver_quote', 'driver_source_page')
    review_findings = []
    for finding in findings:
        insight = finding['insight']
        if insight['id'] in retained_proofs:
            finding = {key: value for key, value in finding.items() if key != 'validated_copy'}
            finding['insight'] = {key: insight[key] for key in evidence_fields if key in insight}
        review_findings.append(finding)
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
    related_ids = {citation['insight_id'] for citation in payload['planned_source_citations']
                   if anchors.intersection(citation.get('source_pages', ()))}
    related_copy = []
    for decision in selection['decisions']:
        iid = decision['insight_id']
        if iid in targets or iid not in related_ids or decision['decision'] != 'include':
            continue
        if page := decision.get('page'):
            related_copy.append(dict(insight_id=iid, title=page['title'], message=page['message'],
                source_context=[{k: item[k] for k in ('scope', 'description')}
                                for item in page.get('source_context', ())]))
    # With literal copy proofs the reviewer can compare the current claim directly.
    # Message-only pages still need the previous question to locate the qualification.
    quote_bound_ids = {iid for iid, proof in retained_proofs.items()
                       if proof['source_context'] or proof['context_evidence']}
    return {
        **payload,
        'findings': review_findings,
        'earlier_review_questions': {iid: questions for iid, questions in
            payload.get('earlier_review_questions', {}).items() if iid in targets and iid not in quote_bound_ids},
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
        'related_audience_copy': related_copy,
        'settled_selection_ids': selection['ordered_insight_ids'],
        # Qualitative qualifications can belong to a related measure. Never
        # trim these original pages to just the target's numeric row locations.
        'source_pages': payload.get('source_pages', []),
        # Place the addressed audience text after the reference material. A
        # reviewer can locate each proposed correction by its exact current copy.
        'source_context_edit_slots': {d['insight_id']: {
            f'context-{i}': item for i,item in enumerate(d['page'].get('source_context', ()))}
            for d in audience_decisions if d.get('page')},
        **(dict(revised_source_descriptions=changes) if changes else {}),
    }
