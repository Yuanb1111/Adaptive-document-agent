import pytest

from adaptive_document_agent.agent.compact_summary import SummarySynthesisDraft
from adaptive_document_agent.agent.summary_body_allocation import (
    SummaryBodyAllocation, apply_body_allocation, reallocate_body)
from tests.test_summary_content_repair_v122 import draft


def test_allocation_moves_exact_original_copy_and_evidence_without_mutating_input():
    original = draft()
    class Client:
        def generate_structured(self, messages, schema, **kwargs):
            assert schema.__name__ == 'SummaryBodyAllocation'
            from pydantic import ValidationError
            for mapping in [dict(b0_0='body'), dict(b0_0='body', b0_1='appendix_0'),
                            dict(b0_0='body', b0_1='body'),
                            dict(b0_0='body', b0_1='appendix_1', b1_0='body')]:
                with pytest.raises(ValidationError):
                    schema(placements=mapping)
            return schema(placements=dict(b0_0='body', b0_1='appendix_1'))
    revised = reallocate_body(Client(), original, [], SummarySynthesisDraft, {}, limit=1)
    assert revised.pages[0].items == original.pages[0].items[:1]
    assert [i.model_dump() for i in revised.pages[1].items] == [
        i.model_dump() for i in original.pages[1].items + original.pages[0].items[1:]]
    assert revised.model_dump(exclude={'pages'}) == original.model_dump(exclude={'pages'})
    assert len(original.pages[0].items) == 2 and len(original.pages[1].items) == 1


@pytest.mark.parametrize('target', [0, 10])
def test_moves_cannot_target_body_or_unknown_page(target):
    allocation = SummaryBodyAllocation(body_items=[dict(page_index=0, item_index=0)],
        appendix_moves=[dict(page_index=0, item_index=1, appendix_page_index=target)])
    with pytest.raises(ValueError, match='existing appendix'):
        apply_body_allocation(draft(), allocation, SummarySynthesisDraft)


@pytest.mark.parametrize('body,moves', [
    ([(0, 0)], []),
    ([(0, 0), (0, 1)], [(0, 1)]),
    ([(0, 0), (0, 1), (1, 0)], []),
    ([(0, 0), (0, 9)], [(0, 1)]),
])
def test_every_body_paragraph_requires_exactly_one_destination(body, moves):
    allocation = SummaryBodyAllocation(
        body_items=[dict(page_index=p, item_index=i) for p, i in body],
        appendix_moves=[dict(page_index=p, item_index=i, appendix_page_index=1) for p, i in moves])
    with pytest.raises(ValueError, match='each exact body paragraph once'):
        apply_body_allocation(draft(), allocation, SummarySynthesisDraft)


def test_budget_allocation_preserves_complete_source_review_integration():
    from adaptive_document_agent.agent.compact_summary import generate_compact_summary
    from adaptive_document_agent.models.customization import ReportRequirement, ReportRequirements
    from adaptive_document_agent.models.presentation import CompanyProfile
    from adaptive_document_agent.services.summary_validation import presentation_errors
    from tests.test_compact_summary_v111 import fixture, Reviewer
    result, review, authored = fixture()
    authored['pages'][-1]['placement'] = 'appendix'
    review.max_intro_slides = 2
    result.profile.report_requirements = ReportRequirements(items=[ReportRequirement(
        id='length', kind='slide_limit', request_quote='Body 15-20, appendix separate',
        description='Body budget', max_slides=20, slide_scope='body')])
    class Client(Reviewer):
        def generate_structured(self, messages, schema, **kwargs):
            if schema.__name__ == 'SummaryBodyAllocation':
                self.calls.append(schema.__name__)
                return schema(placements=dict(b0_0='body', b1_0='body',
                                               b2_0='appendix_4', b3_0='appendix_4'))
            return super().generate_structured(messages, schema, **kwargs)
    client = Client(authored)
    company = generate_compact_summary(client, result, review, CompanyProfile(summary_review=review),
                                       draft_schema=SummarySynthesisDraft)
    assert client.calls == ['SummarySynthesisDraft', 'SummaryBodyAllocation', 'SummarySynthesisReview']
    assert sum(p.placement == 'body' for p in company.summary_pages) == 2
    assert {i.text for p in company.summary_pages for i in p.items} == {
        i['text'] for p in authored['pages'] for i in p['items']}
    assert not presentation_errors(review, company.summary_pages, result)
