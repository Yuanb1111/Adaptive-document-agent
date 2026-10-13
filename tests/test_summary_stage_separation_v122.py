"""Content repair, schema repair and pagination have independent responsibilities."""
import json
import pytest
from pydantic import ValidationError

from adaptive_document_agent.agent.compact_summary import CompactSummaryDraft, generate_compact_summary
from adaptive_document_agent.models.presentation import CompanyProfile
from adaptive_document_agent.services.llm.base import LLMResponse
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
from tests.test_compact_summary_v111 import fixture, Reviewer


def test_content_omission_then_format_failure_then_six_items_is_recoverable():
    result,review,_ = fixture(12)
    complete = dict(pages=[dict(title='Scheduling services',items=[dict(label='Scheduling',
        text=' '.join(p.facts[0].text for p in review.parts[i:i+2]),
        fact_ids=[f'f{i}',f'f{i+1}']) for i in range(0,12,2)])])
    class Client(Reviewer):
        drafts = 0
        def generate_structured(self,messages,schema,**kwargs):
            if schema is CompactSummaryDraft or schema.__name__ == 'SummarySynthesisRevision':
                self.drafts += 1
                if self.drafts==2:
                    raw = json.dumps({'replacements': 'invalid format'})
                    try: schema.model_validate_json(raw)
                    except ValidationError as exc:
                        raise LLMStructuredOutputError('Schema error',response=LLMResponse(text=raw)) from exc
                value=super().generate_structured(messages,schema,**kwargs)
                if self.drafts==1:value.pages[0].items.pop()
                return value
            return super().generate_structured(messages,schema,**kwargs)
    client=Client(complete)
    company=generate_compact_summary(client,result,review,CompanyProfile(summary_review=review))
    assert client.drafts==3
    assert len(review.plan_audits)==2  # Only the omission consumed content repair.
    assert len(review.plan_audits[1]['draft_format_attempts'])==2
    assert all(len(p.items)<=4 for p in company.summary_pages)
    assert [i.text for p in company.summary_pages for i in p.items]==[i['text'] for i in complete['pages'][0]['items']]
    assert {pid for p in company.summary_pages for i in p.items for pid in i.part_ids}=={p.id for p in review.parts}


def test_format_exhaustion_does_not_restart_editor():
    result,review,draft=fixture(1)
    class Client(Reviewer):
        attempts=0
        def generate_structured(self,messages,schema,**kwargs):
            self.attempts+=1
            raise LLMStructuredOutputError('Bad format',response=LLMResponse(text='{}'))
    client=Client(draft)
    with pytest.raises(ValueError,match='format repair exhausted'):
        generate_compact_summary(client,result,review,CompanyProfile(summary_review=review))
    assert client.attempts==2 and len(review.plan_audits)==1


def test_overflow_paginates_losslessly_without_a_model_rewrite():
    from adaptive_document_agent.agent.compact_summary import compact_input, expand_compact
    from adaptive_document_agent.agent.summary_layout_repair import paginate_draft
    from adaptive_document_agent.services.compact_summary import compact_layout_errors
    _, review, _ = fixture(1)
    _, catalog = compact_input(review)
    sentence = '排班服务须经客户集成和员工培训后交付。'
    original = CompactSummaryDraft(pages=[dict(title='Service delivery', items=[dict(
        label='Scheduling', text=sentence * 50, fact_ids=['f0'])])])
    repaired = dict(pages=[dict(title='Service delivery', items=[dict(
        label='Scheduling', text=sentence * 10, fact_ids=['f0']) for _ in range(5)])])
    class Client(Reviewer):
        attempts = 0
        def generate_structured(self, messages, schema, **kwargs):
            self.attempts += 1
            if self.attempts == 1:
                raise LLMStructuredOutputError('Bad format', response=LLMResponse(text='{}'))
            return super().generate_structured(messages, schema, **kwargs)
    client, audit = Client(repaired), {}
    draft, pages = paginate_draft(client, original, catalog, review, [], audit,
                                  expand_compact, CompactSummaryDraft)
    assert client.attempts == 0
    assert [a['status'] for a in audit['layout_attempts']] == ['success']
    assert ''.join(i.text for p in pages for i in p.items) == original.pages[0].items[0].text
    assert all(i.source_refs[0].part_id == 'part-0' for p in pages for i in p.items)
    assert not compact_layout_errors(pages)


@pytest.mark.parametrize('failure', ['privacy', 'transport', 'cancelled'])
def test_draft_format_repair_never_retries_non_format_failure(failure):
    from concurrent.futures import CancelledError
    from adaptive_document_agent.agent.summary_draft_protocol import author_draft
    from adaptive_document_agent.services.llm.exceptions import PrivacyViolationError, LLMTransportError
    error = {'privacy': PrivacyViolationError, 'transport': LLMTransportError,
             'cancelled': CancelledError}[failure]
    class Client:
        calls = 0
        def generate_structured(self, *args, **kwargs):
            self.calls += 1
            raise error('stop')
    client = Client()
    with pytest.raises(error):
        author_draft(client, [], CompactSummaryDraft, {})
    assert client.calls == 1


def test_shared_title_evidence_survives_pagination_without_broadening_body_evidence():
    from adaptive_document_agent.agent.compact_summary import compact_input, expand_compact
    from adaptive_document_agent.agent.summary_theme_layout import pack_theme_pages
    from adaptive_document_agent.services.summary_validation import presentation_errors
    result, review, _ = fixture(6)
    review.max_intro_slides = None
    fact = review.parts[-1].facts[0]
    fact.text += ' The service supports Program 2024.'
    fact.source_quote = fact.text
    review.parts[-1].source_text = fact.text
    result.document.pages[0].text = ''.join(p.source_text for p in review.parts)
    _, catalog = compact_input(review)
    draft = CompactSummaryDraft(pages=[dict(title='Scheduling and Program 2024', items=[dict(
        label='Scheduling', text=p.facts[0].text * 3, fact_ids=[f'f{i}'])
        for i, p in enumerate(review.parts)])])
    pages = pack_theme_pages(expand_compact(draft, catalog, review))
    assert len(pages) >= 2
    assert '2024' not in pages[0].items[0].source_quote
    errors = presentation_errors(review, pages, result, validate_reading=False, verify_compact_review=False)
    assert not any('title contains unsupported' in e for e in errors)
    pages[0].title = 'Scheduling and Program 2099'
    errors = presentation_errors(review, pages, result, validate_reading=False, verify_compact_review=False)
    assert any('title contains unsupported' in e for e in errors)


def test_editor_and_reviewer_can_cite_full_owned_passage_beyond_selected_reader_quotes():
    from adaptive_document_agent.agent.compact_summary import compact_input, expand_compact
    from adaptive_document_agent.services.compact_summary import compact_item_errors
    result, review, _ = fixture(1)
    part = review.parts[0]
    part.source_text = 'Cash was RMB219.0\nmillion. Liquidity would last 10.6 months under the stated burn assumption.'
    part.facts[0].text = 'Cash was RMB219.0 million.'
    part.facts[0].source_quote = 'Cash was RMB219.0'
    result.document.pages[0].text = part.source_text
    payload, catalog = compact_input(review)
    assert len(part.facts) == 2 and part.facts[1].evidence_only
    assert part.facts[1].source_quote == part.source_text
    assert len(payload['parts'][0]['facts']) == 1
    assert payload['parts'][0]['facts'][0]['evidence_only'] is True
    compact_input(review)
    assert len(part.facts) == 2  # Repeated planning does not duplicate evidence.
    draft = CompactSummaryDraft(pages=[dict(title='Liquidity', items=[dict(label='Cash',
        text='Cash was RMB219.0 million.', fact_ids=['f0'])])])
    item = expand_compact(draft, catalog, review)[0].items[0]
    assert not compact_item_errors(item, review, result)
    item.text = 'Cash was RMB999.0 million.'
    assert compact_item_errors(item, review, result)
