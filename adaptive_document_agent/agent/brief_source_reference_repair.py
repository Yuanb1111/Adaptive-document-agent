"""Execute explicit same-page evidence additions; never infer a missing citation."""
from adaptive_document_agent.models.executive_brief import BriefQuote, ExecutiveBriefItem


def owned_evidence_options(item, catalog):
    pages = {quote.page for quote in item.evidence}
    existing = {(quote.page, quote.text) for quote in item.evidence}
    return {ref: value for ref, value in (catalog or {}).items()
            if value['page'] in pages and (value['page'], value['text']) not in existing}


def append_owned_evidence(item, refs, options):
    if len(refs) != len(set(refs)) or any(ref not in options for ref in refs):
        raise ValueError('Evidence additions require distinct supplied same-page references.')
    evidence = [*item.evidence, *(BriefQuote.model_validate(options[ref]) for ref in refs)]
    if len({(q.page, q.text) for q in evidence}) != len(evidence):
        raise ValueError('Evidence additions cannot duplicate an existing quotation.')
    # Enforce the original item schema, including the four-quotation ceiling.
    # Literal page/excerpt verification and independent meaning review follow.
    return ExecutiveBriefItem.model_validate({**item.model_dump(), 'evidence': evidence})
