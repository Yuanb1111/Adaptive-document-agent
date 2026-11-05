"""Retry a complete retained merge reply against current source and validators."""
import json

from adaptive_document_agent.models import PresentationTopicSelection, ValidationIssue
from .coverage_delta_review import TopicCoverageDelta, _decisions, _merge, finalize_decisions
from .coverage_review_binding import source_fingerprint
from .presentation_topic_selector import PresentationTopicSelector, series_directory
from .topic_coverage_review import TopicCoverageReview, uncovered_series


def replay_merge(issue, previous):
    """Return a new coverage receipt only if every original decision can be verified."""
    record = json.loads(issue.message)
    _, lookup = series_directory(previous)
    if (record.get('wire_contract') != 'independent-coverage-delta-v1'
            or record.get('unreviewed_series_ids') != []
            or record.get('source_fingerprint') != source_fingerprint(lookup)):
        return None
    original = PresentationTopicSelection.model_validate(record['original_selection'])
    if original != previous.presentation_topics:
        return None
    primary = {p for start, end in previous.profile.analysis_page_ranges for p in range(start, end + 1)}
    candidates = uncovered_series(original, lookup, primary)
    if candidates != record['candidate_series_ids'] or candidates != list(issue.related_ids):
        return None
    decisions = {}
    for batch in record['batches']:
        ids = batch['series_ids']
        if (decisions.keys() & set(ids) or batch['source_observation_ids'] !=
                {sid: [o.id for o in lookup[sid]] for sid in ids}):
            return None
        decisions.update(_decisions(TopicCoverageDelta.model_validate(batch['review']), ids))
    if set(decisions) != set(candidates):
        return None
    merge = record['merge']
    for reduction in merge.get('reductions', []):
        ids = reduction['series_ids']
        if any(decisions[sid].decision != 'include' for sid in ids):
            return None
        decisions.update(_decisions(TopicCoverageDelta.model_validate(reduction['review']), ids))
    provisional = [sid for sid in candidates if decisions[sid].decision == 'include']
    if provisional != merge['provisional_series_ids']:
        return None
    validate = PresentationTopicSelector.validator_for(previous)
    reply = TopicCoverageReview.model_validate(merge['attempts'][-1]['review'])
    current, final = _merge(reply, original, provisional, lookup, primary, validate)
    decisions.update(final)
    finalize_decisions(current, decisions, candidates, lookup, primary, validate)
    record['review'] = {**current.model_dump(mode='json'),
                        'coverage_decisions': [decisions[sid].model_dump() for sid in candidates]}
    record['merge'] = {**merge, 'status': 'complete', 'revalidated_from_retained_reply': True}
    record.pop('reason', None)
    return ValidationIssue(code='presentation_topic_coverage_review', stage='presentation', severity='info',
                           related_ids=candidates, message=json.dumps(record, ensure_ascii=False))
