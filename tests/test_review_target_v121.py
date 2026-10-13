"""A source cover or stale slide verdict repairs the reviewer, not valid copy."""
import pytest

from adaptive_document_agent.agent.compact_summary import CompactSummaryReview, generate_compact_summary
from adaptive_document_agent.models.presentation import CompanyProfile
from tests.test_compact_summary_v111 import fixture, Reviewer


@pytest.mark.parametrize('wrong', ['cover', 'missing', 'other_slide', 'partial'])
@pytest.mark.parametrize('persistent', [False, True])
@pytest.mark.parametrize('accepted', [False, True])
def test_wrong_review_target_retries_same_generated_copy(wrong, persistent, accepted):
    result, review, draft = fixture(30)
    class Client(Reviewer):
        reviews = 0
        original = None
        def generate_structured(self, messages, schema, **kwargs):
            if schema is not CompactSummaryReview:
                return super().generate_structured(messages,schema,**kwargs)
            self.reviews += 1
            if self.reviews == 1:
                self.original = messages[:2]
            else:
                assert messages[:2] == self.original
                assert 'opening_target' in messages[-1]['content']
            value = super().generate_structured(messages[:2],schema,**kwargs)
            if self.reviews == 1 or persistent:
                value.opening_accepted = accepted
                value.opening_reason = 'The cover only names the issuer.'
                if wrong == 'cover':
                    value.opening_item_texts = ['GLOBAL OFFERING']
                elif wrong == 'missing':
                    value.opening_slide_id = None
                    value.opening_item_texts = None
                elif wrong == 'other_slide':
                    value.opening_slide_id = 'compact_summary_2'
                else:
                    value.opening_item_texts = []
            return value
    client = Client(draft)
    company = CompanyProfile(summary_review=review)
    if persistent:
        with pytest.raises(ValueError,match='review protocol failed'):
            generate_compact_summary(client,result,review,company)
        assert not company.summary_pages
    else:
        generate_compact_summary(client,result,review,company)
        assert company.summary_pages
    assert client.calls == ['CompactSummaryDraft','CompactSummaryReview','CompactSummaryReview']
    assert len(review.plan_audits)==1
    assert review.plan_audits[0]['compact_review_attempts'][0]['status']=='invalid_target'


def test_correctly_bound_rejection_is_not_auto_accepted():
    result, review, draft = fixture(10)
    class Client(Reviewer):
        def generate_structured(self,messages,schema,**kwargs):
            value = super().generate_structured(messages,schema,**kwargs)
            if schema is CompactSummaryReview:
                value.opening_accepted = False
                value.opening_reason = 'Scope is missing from the generated introduction.'
            return value
    client = Client(draft)
    with pytest.raises(ValueError,match='repeated the rejected draft'):
        generate_compact_summary(client,result,review,CompanyProfile(summary_review=review))
    assert client.calls == ['CompactSummaryDraft','CompactSummaryReview','CompactSummaryDraft']
