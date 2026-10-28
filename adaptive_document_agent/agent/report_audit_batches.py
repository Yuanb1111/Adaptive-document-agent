"""Bounded transport batches and exact coverage accounting for assurance review."""
from copy import deepcopy

AUDIT_SCOPE_BATCH_SIZE = 3
BATCHED_AUDIT_CONTRACT = 'report-audit-scope-v174-independent-unknowns'
# The source-proof contract remains distinct from route/reasoning capacity.
AUDIT_REQUEST_STRATEGY = 'audit-scope-exact-unknown-review-v174'


class AuditReviewContractError(ValueError):
    """The reviewer returned an invalid binding-verdict ledger, not a rejection."""


def batch_targets(context):
    """Keep nearby source rows together; every target is reviewed exactly once.

    This orders transport only. It neither assigns assurance nor selects which
    evidence is useful. All source pages and check context remain in each call.
    """
    observations = context['observations']
    def address(observation):
        pages = tuple(sorted(e['page'] for e in observation['evidence']))
        return (pages, observation.get('table_id') or '',
                observation['row_id'] if observation.get('row_id') is not None else -1,
                observation.get('period') or '', observation['id'])
    ordered = sorted(observations, key=address)
    return [[o['id'] for o in ordered[start:start + AUDIT_SCOPE_BATCH_SIZE]]
            for start in range(0, len(ordered), AUDIT_SCOPE_BATCH_SIZE)]


def batch_context(context, observation_ids):
    by_id = {o['id']: o for o in context['observations']}
    return {**context, 'observations': [by_id[oid] for oid in observation_ids],
            'scope': context['scope'] + ' Review ONLY these batch targets. Other targets are '
                     'assigned to separate batches; do not infer anything about them. '
                     'All source pages and source-check context are retained in full.'}


def validate_review(draft, review, context=None):
    expected = {b.observation_id for b in draft.bindings}
    verdicts = {v.observation_id: v for v in review.verdicts}
    if len(verdicts) != len(review.verdicts) or set(verdicts) != expected:
        raise AuditReviewContractError(
            'Independent audit review must cover every exact proposed binding once and only those bindings. '
            f'Expected verdict observation_ids: {sorted(expected)}; '
            f'received: {[v.observation_id for v in review.verdicts]}. '
            'Unresolved IDs belong only in unresolved_accepted/unresolved_reason; '
            'when bindings is empty, verdicts must be [].')
    errors = [v.reason for v in review.verdicts if not v.accepted]
    if draft.unresolved_observation_ids and not review.unresolved_accepted:
        errors.append(review.unresolved_reason)
    if errors:
        raise ValueError('; '.join(errors))
    from .report_audit_counterpart import validate_covered_sources
    validate_covered_sources(draft, review, context)


def completed_batch(context, record):
    """Recheck persisted approval against its exact sources and target partition."""
    from .report_audit_scope import AuditScopeDraft, AuditScopeReview, _fingerprint, _validate
    if not isinstance(record, dict):
        raise ValueError('Audit batch must be a source-bound record.')
    ids = record['observation_ids']
    if (record.get('status') != 'complete' or not isinstance(ids, list)
            or not 1 <= len(ids) <= AUDIT_SCOPE_BATCH_SIZE
            or any(not isinstance(oid, str) for oid in ids) or len(set(ids)) != len(ids)):
        raise ValueError('Audit batch is unfinished or has an invalid target partition.')
    scoped = batch_context(context, ids)
    if record['context_fingerprint'] != _fingerprint(scoped):
        raise ValueError('Audit batch source context is stale.')
    draft = AuditScopeDraft.model_validate(record['draft'])
    review = AuditScopeReview.model_validate(record['review'])
    _validate(draft, scoped)
    validate_review(draft, review, scoped)
    return draft, review


def aggregate_batches(context, batches):
    """Only a complete, independently approved partition can become acceptance."""
    from .report_audit_scope import AuditScopeDraft, AuditScopeReview, _validate
    expected = {o['id'] for o in context['observations']}
    seen, bindings, unknown, verdicts, ledger = set(), [], [], [], []
    for number, record in enumerate(batches, 1):
        ids = set(record['observation_ids'])
        if ids & seen or not ids <= expected:
            raise ValueError('Audit batches duplicate or invent target observations.')
        draft, review = completed_batch(context, record)
        seen.update(ids)
        bindings.extend(draft.bindings)
        unknown.extend(draft.unresolved_observation_ids)
        verdicts.extend(review.verdicts)
        by_id = {b.observation_id: b for b in draft.bindings}
        for oid in record['observation_ids']:
            ledger.append(dict(observation_id=oid, batch=number,
                disposition=by_id[oid].status if oid in by_id else 'unknown',
                independently_accepted=True))
    if seen != expected:
        raise ValueError('Audit batches do not cover every target observation.')
    # Source-specific explanations remain verbatim in each completed batch.
    # These references avoid truncating or reinterpreting their semantic text.
    draft = AuditScopeDraft(bindings=bindings, unresolved_observation_ids=unknown,
        unresolved_reason='See the completed batch records for each source-specific unknown disposition.' if unknown else '')
    review = AuditScopeReview(verdicts=verdicts, unresolved_accepted=True,
        unresolved_reason='Every batch independently approved its full unresolved-observation scope; see batch review reasons.')
    _validate(draft, context)
    validate_review(draft, review, context)
    return draft, review, ledger


def resumable_batches(result, context):
    """Resume only fully approved batches from the latest identical failed run."""
    import json
    from .report_audit_scope import _fingerprint
    latest = next((w for w in reversed(result.validation_warnings)
                   if w.code in {'report_audit_scope_review', 'report_audit_scope_unresolved'}), None)
    if latest is None or latest.code != 'report_audit_scope_unresolved':
        return {}
    try:
        audit = json.loads(latest.message)
        if (not isinstance(audit, dict) or audit.get('contract') != BATCHED_AUDIT_CONTRACT
                or audit.get('request_strategy') != AUDIT_REQUEST_STRATEGY
                or audit.get('fingerprint') != _fingerprint(context)):
            return {}
        ready, seen = {}, set()
        records = audit.get('batches', [])
        if not isinstance(records, list):
            return {}
        for record in records:
            if not isinstance(record, dict):
                return {}
            if record.get('status') != 'complete':
                continue
            completed_batch(context, record)
            if seen.intersection(record['observation_ids']):
                raise ValueError('Completed audit checkpoint partitions must not overlap.')
            seen.update(record['observation_ids'])
            ready[tuple(record['observation_ids'])] = deepcopy(record)
        return ready
    except (ValueError, KeyError, TypeError):
        return {}


def _length_failure(record):
    """Only an explicit provider length finish permits a smaller target request."""
    attempts = record.get('attempts', [])
    if not attempts:
        return False
    latest = attempts[-1]
    physical = latest.get('review_output_attempts') or latest.get('draft_output_attempts') or []
    return bool(physical and physical[-1].get('status') == 'truncated'
                and physical[-1].get('usage', {}).get('finish_reason') == 'length')


def _known_capacity_splits(result, context, capacity_identity=None):
    """Keep proven failures only for the same complete source and request strategy."""
    import json
    from .report_audit_scope import _fingerprint
    if capacity_identity is None:
        return {}
    latest = next((w for w in reversed(result.validation_warnings)
                   if w.code in {'report_audit_scope_review', 'report_audit_scope_unresolved'}), None)
    if latest is None or latest.code != 'report_audit_scope_unresolved':
        return {}
    try:
        audit = json.loads(latest.message)
        # Counterpart proofs changed the response schema, so old capacity
        # failures cannot justify splitting a new request without trying it.
        if (not isinstance(audit, dict) or audit.get('contract') != BATCHED_AUDIT_CONTRACT
                or audit.get('request_strategy') != AUDIT_REQUEST_STRATEGY
                or audit.get('capacity_identity') != capacity_identity
                or audit.get('fingerprint') != _fingerprint(context)):
            return {}
        known = {}
        for record in [*audit.get('capacity_splits', []), *audit.get('batches', [])]:
            ids = record['observation_ids']
            if (1 < len(ids) <= AUDIT_SCOPE_BATCH_SIZE and len(ids) == len(set(ids))
                    and record.get('context_fingerprint') == _fingerprint(batch_context(context, ids))
                    and record.get('status') in {'split', 'failed'} and _length_failure(record)):
                known[tuple(ids)] = deepcopy(record)
        return known
    except (ValueError, KeyError, TypeError, AttributeError):
        return {}


def _retain_checkpoint_partitions(context, partitions, ready, known):
    """Keep untouched source-bound work when an earlier group fails again."""
    batches = [record for part in partitions for record in part['batches']]
    splits = [record for part in partitions for record in part['capacity_splits']]
    visited = {tuple(record['observation_ids']) for record in [*batches, *splits]}
    covered = {oid for record in batches if record.get('status') == 'complete'
               for oid in record['observation_ids']}
    for ids, record in ready.items():
        # Current records take precedence. Accepted parent/child records may
        # never overlap. A failed parent is diagnostic only, so retain any
        # independently accepted children for the next retry alongside it.
        if ids in visited or covered.intersection(ids):
            continue
        completed_batch(context, record)
        batches.append(deepcopy(record))
        covered.update(ids)
    for ids, record in known.items():
        if ids not in visited:
            splits.append(deepcopy(record))
    order = {oid: position for position, oid in enumerate(
        oid for ids in batch_targets(context) for oid in ids)}
    def source_order(record):
        positions = tuple(sorted(order[oid] for oid in record['observation_ids']))
        return positions[0], -len(positions), positions
    return sorted(batches, key=source_order), sorted(splits, key=source_order)


def review_partitions(gateway, result, context, audit, review_batch, *, progress=None):
    """Split proven truncations down to one target; accepted leaves stay atomic.

    Each initial group has at most three targets. A binary tree has at most 2N-1
    requests, each retaining the same existing finite output/semantic retries.
    Syntax, semantic, privacy, transport and cancellation errors never split.
    """
    from .report_audit_scope import _fingerprint
    from .report_audit_capacity import audit_capacity_identity
    from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
    ready = resumable_batches(result, context)
    from .report_audit_draft_resume import pending_audit_drafts
    pending = pending_audit_drafts(result, context)
    capacity_identity = audit_capacity_identity(gateway, AUDIT_REQUEST_STRATEGY)
    known = _known_capacity_splits(result, context, capacity_identity)
    audit['request_strategy'] = AUDIT_REQUEST_STRATEGY
    audit['capacity_identity'] = capacity_identity
    audit['capacity_splits'] = []

    def children(ids):
        middle = len(ids) // 2
        return [ids[:middle], ids[middle:]]

    def run(ids, partition, worker_gateway=gateway, notify=progress, cancelled=None):
        from concurrent.futures import CancelledError
        if cancelled is not None and cancelled.is_set():
            raise CancelledError('Audit review cancelled after another source group failed')
        if tuple(ids) in ready:
            record = deepcopy(ready[tuple(ids)])
            record['reused_completed_batch'] = True
            partition['batches'].append(record)
            if notify:
                notify(f'Audit qualification: reusing {len(ids)} independently reviewed measures')
            return
        if tuple(ids) in known:
            record = deepcopy(known[tuple(ids)])
            record.update(status='split', children=children(ids), reused_proven_truncation=True)
            partition['capacity_splits'].append(record)
            if notify:
                notify(f'Audit qualification: splitting the previously truncated {len(ids)}-measure request')
            for group in record['children']:
                run(group, partition, worker_gateway, notify, cancelled)
            return
        scoped = batch_context(context, ids)
        record = dict(observation_ids=ids, context_fingerprint=_fingerprint(scoped), status='pending', attempts=[])
        if tuple(ids) in pending:
            record['retained_unreviewed_draft'] = deepcopy(pending[tuple(ids)])
        partition['batches'].append(record)
        if notify:
            notify(f'Linking audit qualifications: reviewing {len(ids)} measures')
        try:
            review_batch(worker_gateway, scoped, record)
        except Exception as exc:
            record.update(status='failed', error=str(exc))
            output = exc.response if isinstance(exc, LLMStructuredOutputError) else None
            truncated = output is not None and output.usage is not None and output.usage.finish_reason == 'length'
            if not truncated or len(ids) <= 1:
                raise
            record.update(status='split', children=children(ids))
            partition['batches'].pop()  # Parent is diagnostic only, never an accepted leaf.
            partition['capacity_splits'].append(record)
            if notify:
                notify(f'Audit qualification: splitting {len(ids)} measures after proven output truncation')
            for group in record['children']:
                run(group, partition, worker_gateway, notify, cancelled)

    original_groups = batch_targets(context)
    partitions = [dict(batches=[], capacity_splits=[]) for _ in original_groups]
    owners = {oid: number for number, ids in enumerate(original_groups) for oid in ids}
    completed = set()
    # Approval reuse does not depend on a still-valid capacity split. A prior
    # 1+2 accepted partition stays accepted when the new wire policy has no
    # evidence that its parent of three would truncate. Only remaining IDs
    # are scheduled; this is resumption, not a new proven capacity subdivision.
    for ids, saved in ready.items():
        record = deepcopy(saved)
        record['reused_completed_batch'] = True
        partitions[min(owners[oid] for oid in ids)]['batches'].append(record)
        completed.update(ids)
        if progress:
            progress(f'Audit qualification: reusing {len(ids)} independently reviewed measures')
    work = [([oid for oid in ids if oid not in completed], partition)
            for ids, partition in zip(original_groups, partitions)]
    work = [(ids, partition) for ids, partition in work if ids]
    groups = [ids for ids, _ in work]
    active_partitions = [partition for _, partition in work]
    workers = min(2, len(groups), max(1, getattr(gateway, 'discovery_workers', 1)))
    audit['workers'] = workers
    try:
        if workers == 1:
            for number, (ids, partition) in enumerate(zip(groups, active_partitions), 1):
                if progress:
                    progress(f'Audit qualification source group {number}/{len(groups)}')
                run(ids, partition)
        elif workers:
            from .report_audit_parallel import review_groups_concurrently
            review_groups_concurrently(gateway, groups, active_partitions, run, workers=workers, progress=progress)
    finally:
        # Workers own separate records. Completion/failure merges in source
        # order only after they drain; nothing becomes globally approved early.
        # Cancelled/unreached groups must not erase approved work from the
        # latest checkpoint, which is the only record a later retry can reuse.
        audit['batches'], audit['capacity_splits'] = _retain_checkpoint_partitions(
            context, partitions, ready, known)
