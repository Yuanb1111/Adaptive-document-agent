"""Recover a completed page when only its proof-backed qualitative wording failed."""

from adaptive_document_agent.services.calendar_claims import literal_calendar_dates
from .compact_publication_copy import _qualitative_description_valid
from .reported_source_context import observation_context_labels
from .retained_description_revision import revise_descriptions
from .retained_page_sources import AuthoredPageErrors


def revise_rejected_descriptions(gateway, iid, failure, *, original, payload, limit, validate):
    attempts = failure.rejected_attempts.get(iid, ())
    reasons = failure.by_insight.get(iid, ())
    description_errors = ('source_context must preserve qualitative meaning',
                          'source_context must be a non-quantitative source explanation')
    if not attempts or not reasons or not all(reason.startswith(description_errors) for reason in reasons):
        return None
    candidate = attempts[-1].page
    owner = payload['pages_to_correct'][iid]
    rows = [*owner['primary_observations'], *owner['source_rows']]
    periods = [row['period'] for row in rows if row.get('period')]
    labels = observation_context_labels(rows)
    dates = [date for q in candidate.all_context_evidence for date in literal_calendar_dates(q.text)]
    probe = candidate.model_copy(deep=True)
    addressed = {}
    for index, item in enumerate(candidate.source_context):
        if _qualitative_description_valid(item, item.proof_quotes, [*periods, *dates], labels):
            continue
        # First establish that its scope, evidence, headline and newly selected
        # companion rows can pass independently. This placeholder never publishes.
        probe.source_context[index].description = 'describes the source discussion'
        addressed[f'context-{index}'] = (
            'Keep the source-stated relationship, population and timing in words. Keep unbound numbers '
            'in the literal proof. Where a source gives a threshold, preserve its lower or upper '
            'direction without implying an exact share, an unstated opposite bound, or an unsupported rank. '
            'Apply the relevant source-verified corrections from the owner review: ' + ' '.join(owner['errors']))
    if not addressed or validate({iid: probe}):
        return None
    revised = revise_descriptions(gateway, candidate, addressed, source_pages=payload['source_pages'],
                                  periods=periods, labels=labels, limit=limit, prior_page=original,
                                  allow_qualitative_copy=True)
    errors = validate({iid: revised})
    if errors:
        raise AuthoredPageErrors(errors, rejected_attempts=failure.rejected_attempts)
    return {iid: revised}
