"""Visible unresolved topic scope, independent of whether a deck was rendered."""
import json


def _resolved_series(result):
    """A fresh complete coverage review can replace a failed historical question.

    It must have current source facts, explicit dispositions and independently
    checked current topic wording. A different draft or merely rendered chart
    cannot clear the missing review.
    """
    if not result.presentation_topics or not result.presentation_topics.topics:
        return set()
    latest = next((w for w in reversed(result.validation_warnings) if w.code in {
        'presentation_topic_coverage_review', 'presentation_topic_coverage_unresolved'}), None)
    if latest is None or latest.code != 'presentation_topic_coverage_review':
        return set()
    from adaptive_document_agent.agent.presentation_topic_selector import series_directory
    from adaptive_document_agent.agent.topic_evidence_review import unreviewed_topics
    from adaptive_document_agent.agent.coverage_review_binding import completed_review_is_current, selection_ids
    try:
        audit = json.loads(latest.message)
        _, lookup = series_directory(result)
        if (not completed_review_is_current(result, audit, lookup)
                or unreviewed_topics(result.presentation_topics, lookup, result)):
            return set()
        decisions = audit['review'].get('coverage_decisions', [])
        return selection_ids(audit['review']) | {d['series_id'] for d in decisions
            if d['decision'] in {'include', 'omit'} and d['reason'].strip()}
    except (ValueError, KeyError, TypeError):
        return set()


def topic_review_gaps(result):
    """Never turn a missing/failed review into a semantic omission decision.

    Exact accepted bindings can clear a recovered request. Historical rejected
    drafts stay in the audit but are not presented as current review failures.
    """
    audits = []
    for issue in result.validation_warnings:
        if issue.code != 'presentation_topic_evidence_review':
            continue
        try:
            value = json.loads(issue.message)
            if isinstance(value, dict):
                audits.append(value)
        except (ValueError, TypeError):
            continue
    accepted = {binding for audit in audits for binding in audit.get('accepted_bindings', [])}
    gaps = {}
    resolved = None
    for audit in audits:
        pending = audit.get('unresolved_topics', [])
        if audit.get('error') and 'unresolved_topics' not in audit:
            pending = [dict(t, topic_id=t.get('id'), reason=audit['error'])
                       for t in audit.get('original_topics', [])]
        for topic in pending:
            if topic.get('binding') in accepted:
                continue
            if resolved is None:
                resolved = _resolved_series(result)
            series = set(topic.get('series_ids', []))
            if series and series <= resolved:
                continue
            key = topic.get('topic_id') or topic.get('id')
            gaps[key] = dict(title=topic.get('title') or key or 'Analytical topic',
                             reason='Source review did not complete; this topic is not verified.',
                             series_ids=topic.get('series_ids', []))
    failed_selection = not result.presentation_topics and any(
        w.code == 'presentation_topic_selection_failed' for w in result.validation_warnings)
    if failed_selection and not gaps:
        gaps['selection'] = dict(title='Analytical topic selection', series_ids=[],
            reason='Question selection did not complete. The retained charts do not establish analytical coverage.')
    return list(gaps.values())


def require_topic_review(result):
    gaps = topic_review_gaps(result)
    if gaps:
        raise ValueError('Analytical topic review incomplete. Unverified scope: '
                         + '; '.join(gap['title'] for gap in gaps)
                         + '. Retained evidence is available; retry reporting before final delivery.')


def coverage_review_gaps(result):
    """Name the evidence whose final include/omit disposition is unfinished."""
    latest = next((w for w in reversed(result.validation_warnings) if w.code in {
        'presentation_topic_coverage_review', 'presentation_topic_coverage_unresolved'}), None)
    if latest is None or latest.code != 'presentation_topic_coverage_unresolved':
        return []
    from adaptive_document_agent.agent.presentation_topic_selector import series_directory
    _, lookup = series_directory(result)
    labels = {}
    # Even reviewed deltas remain provisional until their final merge passes.
    # related_ids is the complete request inventory, not a sampled omission list.
    for sid in latest.related_ids:
        group = lookup.get(sid, [])
        if group:
            metrics = list(dict.fromkeys(o.metric_original for o in group))
            periods = list(dict.fromkeys(o.period for o in group if o.period))
            title = ', '.join(metrics) + (' (' + ', '.join(periods) + ')' if periods else '')
            labels[title] = dict(title=title, series_ids=[sid],
                reason='The final decision to include or omit this evidence did not complete.')
    return list(labels.values()) or [dict(title='Unselected source evidence', series_ids=[],
        reason='Its coverage review did not complete; the retained charts do not establish complete coverage.')]
