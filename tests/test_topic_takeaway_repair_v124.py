import json
import pytest

from tests.test_topic_scope_recovery_regressions import _synthetic_result
from adaptive_document_agent.agent.topic_plan_compiler import compile_topic_plan
from adaptive_document_agent.agent.topic_takeaway_repair import repair_withheld_takeaways, TakeawayCorrection
from adaptive_document_agent.agent.presentation_topic_scope_recovery import withheld_topic_ids
from adaptive_document_agent.validation.claim_validator import ClaimValidator


def test_topic_accepts_signed_accounting_cells_but_rejects_an_unreported_amount():
    from adaptive_document_agent.agent.presentation_topic_selector import PresentationTopicSelector
    from tests.test_topic_coverage_review import _observation, _topic
    from adaptive_document_agent.models import PresentationTopicSelection
    observations = [_observation('Cash flow', 'FY2023', -100000),
                    _observation('Cash flow', 'FY2024', -200000)]
    for o, raw in zip(observations, ['(100)', '(200)']):
        o.raw_value, o.raw_unit, o.unit_scale = raw, 'RMB in thousands', 1000
        o.currency, o.unit = 'CNY', 'currency'
    topic = _topic('cash')
    topic.takeaway = 'Cash flow was RMB(100) thousand in FY2023 and RMB(200) thousand in FY2024.'
    selection = PresentationTopicSelection(topics=[topic])
    PresentationTopicSelector._validate(selection, {'cash': observations})
    topic.takeaway = 'Cash flow was RMB(999) thousand in FY2024.'
    with pytest.raises(ValueError, match='unsupported numeric claims'):
        PresentationTopicSelector._validate(selection, {'cash': observations})


@pytest.mark.parametrize('valid', [True, False])
def test_withheld_claim_requires_a_corrected_validated_takeaway(valid):
    result = _synthetic_result('metric_alias')
    plan = compile_topic_plan(result)
    assert withheld_topic_ids(plan) == {'scope'}
    original = result.presentation_topics
    source = result.model_dump(include={'observations', 'charts'})
    rejected = original.topics[0].takeaway
    class Gateway:
        calls = 0
        def generate_structured(self, messages, response_model, **kwargs):
            self.calls += 1
            assert 'source_observations' in messages[1]['content']
            return TakeawayCorrection(takeaway=(
                'Loss for the year amounted to USD 140 in FY2023 and USD 230 in FY2025.'
                if valid else rejected))
    gateway = Gateway()
    repaired = repair_withheld_takeaways(gateway, result, plan)
    assert result.presentation_topics is original
    assert result.model_dump(include={'observations', 'charts'}) == source
    audits = [json.loads(i.message) for i in result.validation_warnings if i.code == 'presentation_topic_takeaway_repair']
    if valid:
        assert not withheld_topic_ids(repaired)
        assert audits[-1]['status'] == 'accepted'
        assert gateway.calls == 1
        assert not ClaimValidator().validate_plan(repaired, result.observations, result.charts)
    else:
        assert withheld_topic_ids(repaired) == {'scope'}
        assert original.topics[0].takeaway == rejected
        assert all(a['status'] == 'rejected' for a in audits)
        assert gateway.calls == 2

@pytest.mark.parametrize('title', ['Reported loss measures', 'Loss for the year rose'])
def test_repair_validates_title_and_takeaway_atomically(title):
    result = _synthetic_result('metric_alias')
    topic = result.presentation_topics.topics[0]
    topic.title = 'Loss for the year widened'
    topic.takeaway = 'Loss for the year amounted to USD 140 in FY2023 and USD 230 in FY2025 in the reported source periods.'
    original = topic.model_dump()
    plan = compile_topic_plan(result)
    assert withheld_topic_ids(plan) == {'scope'}

    class Gateway:
        def generate_structured(self, messages, response_model, **kwargs):
            return TakeawayCorrection(title=title, takeaway=topic.takeaway)

    repaired = repair_withheld_takeaways(Gateway(), result, plan)
    if title == 'Reported loss measures':
        assert not withheld_topic_ids(repaired)
        assert topic.title == title
        assert topic.takeaway == original['takeaway']
        assert topic.question == original['question']
        assert topic.series_ids == original['series_ids']
        audit = json.loads(result.validation_warnings[-1].message)
        assert audit['original_title'] == original['title']
        assert audit['proposed_title'] == title
    else:
        assert withheld_topic_ids(repaired) == {'scope'}
        assert topic.model_dump() == original
