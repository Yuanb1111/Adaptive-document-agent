"""Layout fallback for already model-authored, source-validated reading facts."""
from .summary_editorial import EditorialItem, EditorialPage, SummaryEditorialDraft, editorial_parts, expand_editorial
from adaptive_document_agent.models.summary import SummaryPartDecision
from adaptive_document_agent.utils.ids import stable_id


def reading_presentation(review, result, response_model):
    """Retain every reading fact when editorial transport/rewriting fails.

    The reading model has already decided source scope, part meaning and factual
    summaries. Python makes no new claims or importance choices: it lays out all
    those facts with their exact citations and then runs the normal gates.
    """
    from adaptive_document_agent.services.summary_validation import presentation_errors
    payload, catalog = editorial_parts(review.parts)
    pages, decisions = [], []
    for part in payload:
        included = part['role'] == 'content'
        decisions.append(SummaryPartDecision(part_id=part['id'], decision='include' if included else 'omit',
            reason='Retain every model-authored reading fact.' if included else 'Reading model classified this as heading/layout.'))
        if not included:
            continue
        title = part['facts'][0]['label']  # Already authored by the reading model.
        from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator
        if PresentationPlanValidator._numbers(title) - PresentationPlanValidator._numbers(
                ' '.join(f['source_quote'] for f in part['facts'])):
            title = 'Introduction'
        for offset in range(0,len(part['facts']),4):
            pages.append(EditorialPage(id=stable_id('reading_layout',part['id'],offset),title=title,
                source_section=title,items=[EditorialItem(fact_id=f['id'],label=f['label'],text=f['text'])
                                           for f in part['facts'][offset:offset+4]]))
    # No model response quota applies to deterministic layout of retained facts.
    draft = SummaryEditorialDraft.model_construct(summary_pages=pages, summary_decisions=decisions,
                                                   name='', name_fact_id='')
    response = expand_editorial(draft,catalog,response_model)
    for page in response.summary_pages:
        for item in page.items:
            item.reading_fact_copy = True
        if PresentationPlanValidator._numbers(page.title) - PresentationPlanValidator._numbers(
                ' '.join(item.source_quote for item in page.items)):
            page.title = 'Introduction'
    review.decisions = decisions
    errors = presentation_errors(review,response.summary_pages,result,validate_reading=False)
    if errors:
        raise ValueError('Reading layout failed validation: '+'; '.join(errors))
    from adaptive_document_agent.models.presentation import CompanyProfile
    return CompanyProfile(summary_pages=response.summary_pages,summary_review=review)
