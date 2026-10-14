"""Names cannot replace source characteristics; quoted copy must have the right binding."""
from types import SimpleNamespace
from copy import deepcopy
import pytest

from adaptive_document_agent.agent.compact_summary import CoveragePartVerdict, compact_input, generate_compact_summary
from adaptive_document_agent.agent.summary_coverage import coverage_errors
from adaptive_document_agent.models.presentation import CompanyProfile
from adaptive_document_agent.services.introduction_audience import audience_part_ids
from tests.test_compact_summary_v111 import fixture, Reviewer
from tests.test_total_file_budget_v130 import choose


def verdict(checks):
    return CoveragePartVerdict(part_id='product', accepted=True, reason='Names are present.', coverage=checks)


def check(index=0, covered=True, quote='Lightweight and compact for desktop deployment.'):
    return dict(meaning_index=index, covered=covered, summary_quote=quote if covered else '',
                reason='The defining characteristics must be preserved.')


def pages(text, *, part='product', placement='body'):
    return [SimpleNamespace(placement=placement, items=[SimpleNamespace(text=text, part_ids=[part])])]


MEANINGS = [dict(meaning='Lightweight, compact design supports desktop deployment.',
                 source_quote='Lightweight and compact for desktop deployment.')]


def test_overall_acceptance_cannot_override_explicit_missing_central_meaning():
    response = verdict([check(covered=False)])
    assert coverage_errors(response, MEANINGS, pages('Magician and M Series.'))


@pytest.mark.parametrize('checks', [[], [check(), check()], [check(index=1)]])
def test_incomplete_duplicate_or_wrong_coverage_indices_fail(checks):
    assert coverage_errors(verdict(checks), MEANINGS, pages(MEANINGS[0]['source_quote']))


def test_source_quote_and_unbound_other_copy_cannot_substitute_for_visible_bound_copy():
    rendered = pages('Magician and M Series.') + pages(MEANINGS[0]['source_quote'], part='another-source')
    assert coverage_errors(verdict([check()]), MEANINGS, rendered)


def test_complete_bound_appendix_counts_as_coverage():
    rendered = pages('Magician and M Series.') + pages(MEANINGS[0]['source_quote'], placement='appendix')
    assert not coverage_errors(verdict([check()]), MEANINGS, rendered)


def test_exact_continuations_preserve_words_crossing_layout_boundaries():
    items = [SimpleNamespace(text='Lightweight and com', part_ids=['product'], continuation_group='g', continuation_index=0),
             SimpleNamespace(text='pact for desktop deployment.', part_ids=['product'], continuation_group='g', continuation_index=1)]
    assert not coverage_errors(verdict([check()]), MEANINGS, [SimpleNamespace(items=items)])


@pytest.mark.parametrize('mutation', ['empty', 'unowned', 'duplicate'])
def test_stale_missing_or_unowned_meaning_contract_fails_before_generation(mutation):
    result, review, _ = fixture(1)
    choose(result, review)
    points = review.audience_selection['decisions'][0]['required_meanings']
    if mutation == 'empty': points.clear()
    elif mutation == 'unowned': points[0]['source_quote'] = 'A claim from a different page.'
    else: points.append(deepcopy(points[0]))
    with pytest.raises(ValueError, match='meaning'):
        audience_part_ids(review)


def test_author_and_independent_reviewer_receive_identical_stable_meanings():
    result, review, _ = fixture(1)
    choose(result, review)
    source, _ = compact_input(review)
    assert source['parts'][0]['required_meanings'] == review.audience_selection['decisions'][0]['required_meanings']
    draft = dict(pages=[dict(title='Scheduling service', items=[dict(label='Service scope',
        text=review.parts[0].source_text.strip(), fact_ids=['f0'])])])
    company = generate_compact_summary(Reviewer(draft), result, review, CompanyProfile(summary_review=review))
    final = review.plan_audits[-1]['compact_semantic_review']['parts'][0]
    assert final['accepted'] and final['coverage'][0]['covered']
    assert final['coverage'][0]['summary_quote'] == company.summary_pages[0].items[0].text


def test_export_rechecks_contract_and_missing_checks_in_an_accepted_audit():
    from adaptive_document_agent.services.summary_validation import presentation_errors
    result, review, _ = fixture(1)
    choose(result, review)
    draft = dict(pages=[dict(title='Scheduling service', items=[dict(label='Service scope',
        text=review.parts[0].source_text.strip(), fact_ids=['f0'])])])
    company = generate_compact_summary(Reviewer(draft), result, review, CompanyProfile(summary_review=review))
    review.status = 'complete'
    assert not presentation_errors(review, company.summary_pages, result)
    audit = review.plan_audits[-1]
    saved = deepcopy(audit['compact_semantic_review']['parts'][0]['coverage'])
    audit['compact_semantic_review']['parts'][0]['coverage'] = []
    assert any('independent' in e for e in presentation_errors(review, company.summary_pages, result))
    audit['compact_semantic_review']['parts'][0]['coverage'] = saved
    review.audience_selection['decisions'][0]['required_meanings'][0]['meaning'] += ' Additional central scope.'
    assert any('independent' in e for e in presentation_errors(review, company.summary_pages, result))


def test_false_overall_acceptance_triggers_targeted_repair_and_fresh_independent_review():
    result, review, _ = fixture(1)
    choose(result, review)
    draft = dict(pages=[dict(title='Scheduling service', items=[dict(label='Service scope',
        text='Team AA supports scheduling.', fact_ids=['f0'])])])
    class Client(Reviewer):
        reviews = 0
        def generate_structured(self, messages, schema, **kwargs):
            if schema.__name__ == 'SummarySynthesisRevision':
                self.draft['pages'][0]['items'][0]['text'] = review.parts[0].source_text.strip()
            response = super().generate_structured(messages, schema, **kwargs)
            if schema.__name__ == 'SummaryCoverageReview':
                self.reviews += 1
                if self.reviews == 1:
                    response.parts[0].coverage[0].covered = False
                    response.parts[0].coverage[0].summary_quote = ''
                    response.parts[0].coverage[0].reason = 'The required training condition is missing.'
                    assert response.parts[0].accepted
            return response
    client = Client(draft)
    company = generate_compact_summary(client, result, review, CompanyProfile(summary_review=review))
    assert client.reviews == 2 and len(review.plan_audits) == 2
    assert review.plan_audits[0]['compact_semantic_review']['parts'][0]['accepted'] is False
    assert 'training' in company.summary_pages[0].items[0].text
    assert review.plan_audits[-1]['compact_semantic_review']['parts'][0]['coverage'][0]['covered']


def test_measured_layout_feedback_merges_groups_without_dropping_required_meanings():
    import json
    from adaptive_document_agent.agent.compact_summary import CompactSummaryDraft
    result, review, _ = fixture(3)
    review.max_intro_slides = 1
    choose(result, review, selected=('part-0', 'part-1', 'part-2'))
    draft = dict(pages=[dict(title='Scheduling service', items=[dict(label='Service scope',
        text=p.source_text.strip(), fact_ids=[f'f{i}'])]) for i, p in enumerate(review.parts)])
    class Client(Reviewer):
        author_calls = 0
        def generate_structured(self, messages, schema, **kwargs):
            if issubclass(schema, CompactSummaryDraft):
                self.author_calls += 1
                if self.author_calls == 2:
                    record = json.loads(messages[-2]['content'].split('\n',1)[1].rsplit('\n',1)[0])
                    assert len(record['physical_groups']) == 3
                    assert 'required_meanings' in messages[-1]['content']
                    self.draft = dict(pages=[dict(title='Scheduling service',
                        items=[pg['items'][0] for pg in draft['pages']])])
            return super().generate_structured(messages, schema, **kwargs)
    client = Client(draft)
    company = generate_compact_summary(client, result, review, CompanyProfile(summary_review=review))
    assert client.author_calls == 2 and len(company.summary_pages) == 1
    final = review.plan_audits[-1]['compact_semantic_review']['parts']
    assert len(final) == 3 and all(v['accepted'] and v['coverage'][0]['covered'] for v in final)


def test_binding_repair_reuses_existing_copy_and_rechecks_both_affected_parts():
    result, review, _ = fixture(2)
    scope = 'Team AA supports appointment scheduling for clinics and laboratories across supported operating sites.'
    training = 'Staff training is required before service delivery and prepares personnel for scheduling services across supported operating sites.'
    source_lines = [scope + ' Staff training is required before service delivery.\n', training + '\n']
    for part, text in zip(review.parts, source_lines):
        part.source_text = text
        part.facts[0].text = part.facts[0].source_quote = text.strip()
    result.document.pages[0].text = review.source_blocks[0].text = ''.join(source_lines)
    review.source_blocks[0].char_end = len(review.source_blocks[0].text)
    choose(result, review, selected=('part-0', 'part-1'))
    draft = dict(pages=[dict(title='Scheduling service', items=[
        dict(label='Service scope', text=scope, fact_ids=['f0']),
        dict(label='Training prerequisite', text=training, fact_ids=['f1'])])])
    class Client(Reviewer):
        def generate_structured(self, messages, schema, **kwargs):
            if schema.__name__ == 'SummarySynthesisRevision':
                self.draft['pages'][0]['items'][1]['fact_ids'].append('f0')
            response = super().generate_structured(messages, schema, **kwargs)
            if schema.__name__ == 'SummaryCoverageReview':
                bound = 'f0' in self.draft['pages'][0]['items'][1]['fact_ids']
                for v in response.parts:
                    v.coverage[0].covered = bound if v.part_id == 'part-0' else True
                    v.coverage[0].summary_quote = training if v.coverage[0].covered else ''
                    v.coverage[0].reason = 'Training exists, but must be bound to this part.'
            return response
    company = generate_compact_summary(Client(draft), result, review, CompanyProfile(summary_review=review))
    assert [it.text for pg in company.summary_pages for it in pg.items] == [scope, training]
    assert company.summary_pages[0].items[1].part_ids == ['part-1', 'part-0']
    assert len(review.plan_audits) == 2 and not review.plan_audits[-1]['retained_part_reviews']
    assert all(v['accepted'] for v in review.plan_audits[-1]['compact_semantic_review']['parts'])


def test_inexact_review_quote_repairs_verdict_without_rewriting_valid_copy():
    from adaptive_document_agent.agent.compact_summary import CompactSummaryDraft
    result, review, _ = fixture(1)
    choose(result, review)
    text = review.parts[0].source_text.strip()
    draft = dict(pages=[dict(title='Scheduling service', items=[dict(label='Service scope',
        text=text, fact_ids=['f0'])])])
    class Client(Reviewer):
        authors = 0
        reviews = 0
        original_review = None
        def generate_structured(self, messages, schema, **kwargs):
            if issubclass(schema, CompactSummaryDraft): self.authors += 1
            if schema.__name__ == 'SummaryCoverageReview':
                self.reviews += 1
                if self.original_review is None: self.original_review = deepcopy(messages)
                else:
                    assert messages[:2] == self.original_review
                    assert 'SAME pages' in messages[-1]['content']
                response = super().generate_structured(self.original_review, schema, **kwargs)
                if self.reviews == 1:
                    response.parts[0].coverage[0].summary_quote = 'A paraphrase absent from visible copy.'
                return response
            return super().generate_structured(messages, schema, **kwargs)
    client = Client(draft)
    company = generate_compact_summary(client, result, review, CompanyProfile(summary_review=review))
    assert client.authors == 1 and client.reviews == 2 and company.summary_pages[0].items[0].text == text
    assert [a['status'] for a in review.plan_audits[-1]['compact_review_attempts']] == ['invalid_target', 'success']
    assert len(review.plan_audits) == 1
