"""Lossless rationale wire compression and fail-closed semantic decision audits."""

import ast
from copy import deepcopy
import json
from pathlib import Path

import pytest

from adaptive_document_agent.agent.analysis_planner import AnalysisPlanner
from adaptive_document_agent.agent.candidate_generator import AnalysisCandidateGenerator
from adaptive_document_agent.agent.value_scorer import AnalysisValueScorer, SemanticCandidateScores, _scoring_payload
from adaptive_document_agent.document_model import DocumentIndex
from adaptive_document_agent.models import (
    AnalysisCandidate, CandidateScore, DocumentProfile, Observation, ParsedDocument, PipelineResult, SourceEvidence,
)
from adaptive_document_agent.services.export import export_json
from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, MockLLMClient, ProviderName
from adaptive_document_agent.services.llm.reasoning_policy import request_reasoning_policy
from adaptive_document_agent.utils.caching import DiskCache


FIXTURE = Path(__file__).parent / "fixtures" / "candidate_scoring_rationales.json"


def scoring_fixture(count=40):
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    catalog = {entry["id"]: entry["text"] for entry in fixture["reason_catalog"]}
    candidates, observations, decisions = [], [], []
    for position in range(count):
        case = fixture["cases"][position % len(fixture["cases"])]
        metric = f"{case['metric']} {position}"
        ids = [f"observation-{position}-{year}" for year in (2023, 2024, 2025)]
        candidates.append(AnalysisCandidate(
            id=f"candidate_{position}", title=f"Compare {metric}", metric=metric,
            analysis_type=case["analysis_type"], dimensions=["region"], observation_ids=ids,
            reason=fixture["source_reason"],
        ))
        for page, (identifier, year, value) in enumerate(zip(ids, (2023, 2024, 2025), (100, 120, 150)), start=1):
            observations.append(Observation(
                id=identifier, metric_original=metric, value=value, raw_value=f"{value}.0", unit="source units",
                period=str(year), dimensions={"region": "Remote"}, confidence=.9,
                evidence=[SourceEvidence(page=page, text=f"{metric}: {value}.0 ({year})", table_id=f"table-{position}",
                                         extraction_method="digital_table", confidence=.9)],
            ))
        decisions.append({
            "candidate_id": candidates[-1].id, "score": case["score"], "rejected": case["rejected"],
            "reason_refs": case["reason_refs"], "reasons": [*case["reasons"], f"Review specifically covers {', '.join(ids)}."],
        })
    compact = {"reason_catalog": fixture["reason_catalog"], "scores": decisions}
    legacy = {"scores": [
        {**{key: value for key, value in item.items() if key != "reason_refs"},
         "reasons": [*(catalog[ref] for ref in item["reason_refs"]), *item["reasons"]]}
        for item in decisions
    ]}
    profile = DocumentProfile(document_type="Unfamiliar mixed evidence report", document_purpose="Compare measured outcomes",
                              metrics=[item.metric for item in candidates])
    return candidates, DocumentIndex(observations), profile, compact, legacy


def run_score(response, *, count=4, maximum=20, cache=None):
    candidates, index, profile, _, _ = scoring_fixture(count)
    client = MockLLMClient([response])
    gateway = LLMGateway(client, LLMSettings(provider=ProviderName.MOCK), cache=cache)
    scores = AnalysisValueScorer(gateway).score(candidates, index, profile, maximum=maximum)
    return scores, client, gateway


def test_full_and_compact_wire_expand_to_identical_ranking_selection_reasons_and_evidence():
    candidates, index, profile, compact, legacy = scoring_fixture()
    before_candidates = [item.model_dump() for item in candidates]
    before_observations = [index.get(identifier).model_dump() for candidate in candidates for identifier in candidate.observation_ids]
    compact_scores, client, gateway = run_score(compact, count=40, maximum=12)
    full_scores, _, _ = run_score(legacy, count=40, maximum=12)
    assert [item.model_dump(exclude={"semantic_audit"}) for item in compact_scores] == [
        item.model_dump(exclude={"semantic_audit"}) for item in full_scores
    ]
    assert len(compact_scores) == len(candidates) == 40
    assert sum(not item.rejected for item in compact_scores) == 12
    assert AnalysisPlanner().plan(compact_scores, index) == AnalysisPlanner().plan(full_scores, index)
    assert [item.model_dump() for item in candidates] == before_candidates
    assert [index.get(identifier).model_dump() for candidate in candidates for identifier in candidate.observation_ids] == before_observations
    assert len(client.calls) == 1
    assert gateway.usage[0]["stage"] == "planner"
    assert gateway.usage[0]["operation"] == "SemanticCandidateScores"
    assert all(item.semantic_audit.decisions[0].score == next(
        decision["score"] for decision in compact["scores"] if decision["candidate_id"] == item.candidate.id
    ) for item in compact_scores)
    assert any("below bounded top-candidate cutoff" in item.reasons and not item.semantic_audit.decisions[0].rejected
               for item in compact_scores)
    assert any("provisional / 暂定" in reason for item in compact_scores if item.rejected for reason in item.reasons)
    assert any("unique denominator caveat" in reason for item in compact_scores if item.rejected for reason in item.reasons)
    wire = lambda value: json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    assert len(wire(compact)) < len(wire(legacy)) * .65


def test_source_reason_interning_is_exact_reversible_and_nonmutating():
    candidates, _, profile, _, _ = scoring_fixture()
    candidates[-1].reason += " Unique final exception."
    candidates[-2].reason = candidates[-2].reason.upper()
    before = [item.model_dump(mode="json") for item in candidates]
    payload = _scoring_payload(candidates, profile)
    assert payload["document_profile"] == profile.model_dump(mode="json")
    restored = []
    for item in payload["candidates"]:
        expanded = dict(item)
        if "source_reason_ref" in expanded:
            expanded["reason"] = payload["source_reason_catalog"][expanded.pop("source_reason_ref")]
        restored.append(expanded)
    assert restored == before
    assert [item.model_dump(mode="json") for item in candidates] == before
    assert payload["candidates"][-1]["reason"] == candidates[-1].reason
    assert payload["candidates"][-2]["reason"] == candidates[-2].reason
    assert len(str(payload)) < len(str({"document_profile": profile.model_dump(mode="json"), "candidates": before}))


def test_request_uses_compact_source_references_and_existing_untrusted_boundaries():
    _, _, _, compact, _ = scoring_fixture()
    _, client, _ = run_score(compact, count=40)
    message = client.calls[0][1]["content"]
    assert message.startswith("<UNTRUSTED_DOCUMENT_CONTENT>\n")
    assert message.endswith("\n</UNTRUSTED_DOCUMENT_CONTENT>")
    payload = ast.literal_eval(message.split("\n", 1)[1].rsplit("\n", 1)[0])
    assert len(payload["candidates"]) == 40
    assert len(payload["source_reason_catalog"]) == 1
    assert all("source_reason_ref" in {**payload.get("candidate_constants", {}), **item}
               for item in payload["candidates"])
    instruction = client.calls[0][0]["content"]
    assert "exceptions" in instruction and "caveats" in instruction and "accepted AND rejected" in instruction


def test_short_or_unique_source_reasons_are_not_expanded_by_reference_overhead():
    candidates, _, profile, _, _ = scoring_fixture(2)
    for candidate in candidates:
        candidate.reason = "x"
    assert "source_reason_catalog" not in _scoring_payload(candidates, profile)
    candidates[1].reason = "X"
    assert "source_reason_catalog" not in _scoring_payload(candidates, profile)


@pytest.mark.parametrize("refs,reasons,catalog,error", [
    (["missing"], ["Unique detail remains auditable."], {}, "unknown rationale reference"),
    ([""], ["Unique detail remains auditable."], {}, "blank rationale reference"),
    (["  "], ["Unique detail remains auditable."], {}, "blank rationale reference"),
    (["r", "r"], [], {"r": "Shared complete reason."}, "duplicate rationale reference"),
    (["r"], [], {"r": "  "}, "blank rationale catalog entry"),
    ([], ["  "], {}, "blank inline rationale"),
    (["r"], [""], {"r": "Useful shared reason."}, "blank inline rationale"),
    ([], [], {}, "no intelligible rationale"),
])
def test_bad_references_and_blank_rationale_quarantine_only_affected_candidate(refs, reasons, catalog, error):
    response = {"reason_catalog": [{"id": key, "text": value} for key, value in catalog.items()], "scores": [
        {"candidate_id": "candidate_0", "score": .99, "rejected": False, "reason_refs": refs, "reasons": reasons},
        {"candidate_id": "candidate_1", "score": .8, "rejected": False, "reasons": ["Independent complete reason."]},
    ]}
    scores, _, _ = run_score(response, count=2)
    bad, good = ({item.candidate.id: item for item in scores}[f"candidate_{position}"] for position in (0, 1))
    assert bad.rejected and not good.rejected
    assert any(error in reason for reason in bad.reasons)
    assert bad.semantic_audit.decisions[0].model_dump() == response["scores"][0]
    assert bad.semantic_audit.decisions[0].rejected is False


@pytest.mark.parametrize("conflicting", [True, False])
def test_duplicate_decisions_are_never_silently_overwritten(conflicting):
    first = {"candidate_id": "candidate_0", "score": .9, "rejected": False, "reasons": ["First specific reason."]}
    second = ({**first, "score": .1, "rejected": True, "reasons": ["Conflicting unique exception."]} if conflicting else first.copy())
    scores, _, _ = run_score({"scores": [first, second]}, count=1)
    assert scores[0].rejected
    assert "model returned multiple candidate decisions" in scores[0].reasons
    assert [item.model_dump(exclude={"reason_refs"}) for item in scores[0].semantic_audit.decisions] == [first, second]
    assert "First specific reason." in scores[0].reasons
    if conflicting:
        assert "Conflicting unique exception." in scores[0].reasons


def test_unknown_ids_unused_catalog_and_missing_decisions_survive_all_rejected_export():
    response = {"reason_catalog": [{"id": "unused", "text": "Keep even unused prose."}, {"id": "blank", "text": "  "}], "scores": [
        {"candidate_id": "invented", "score": .99, "rejected": False, "reason_refs": ["unknown"], "reasons": ["Invented decision."]},
        {"candidate_id": "candidate_0", "score": .1, "rejected": True, "reasons": ["Specific rejection."]},
    ]}
    scores, _, _ = run_score(response, count=2)
    assert {item.candidate.id for item in scores} == {"candidate_0", "candidate_1"}
    assert all(item.rejected for item in scores)
    audit = scores[0].semantic_audit.response_audit
    assert [entry.model_dump() for entry in audit.reason_catalog] == response["reason_catalog"]
    assert audit.unmatched_decisions[0].model_dump() == response["scores"][0]
    assert any("unknown candidate ID" in error for error in audit.validation_errors)
    assert any("model omitted candidate decision" in item.reasons for item in scores)
    assert sum(item.semantic_audit.response_audit is not None for item in scores) == 1
    result = PipelineResult(document=ParsedDocument(document_id="synthetic", sha256="fixture", safe_filename="fixture.pdf", page_count=3),
                            profile=DocumentProfile(), candidate_scores=scores)
    restored = PipelineResult.model_validate_json(export_json(result))
    assert restored.candidate_scores == scores


def test_unused_bad_catalog_entry_does_not_reject_valid_candidate():
    response = {"reason_catalog": [{"id": "unused", "text": " "}], "scores": [
        {"candidate_id": "candidate_0", "score": .9, "reasons": ["Complete inline rationale."]},
    ]}
    scores, _, _ = run_score(response, count=1)
    assert not scores[0].rejected
    assert scores[0].semantic_audit.response_audit.validation_errors


@pytest.mark.parametrize("conflicting", [True, False])
def test_duplicate_catalog_ids_preserve_all_prose_and_quarantine_only_referencing_candidate(conflicting):
    catalog = [
        {"id": "r", "text": "Original shared rationale."},
        {"id": "r", "text": "Conflicting catalog qualification." if conflicting else "Original shared rationale."},
        {"id": "good", "text": "Unambiguous shared rationale."},
    ]
    response = {"reason_catalog": catalog, "scores": [
        {"candidate_id": "candidate_0", "score": .99, "rejected": False, "reason_refs": ["r"], "reasons": ["Keep unique exception."]},
        {"candidate_id": "candidate_1", "score": .8, "rejected": False, "reason_refs": ["good"]},
    ]}
    scores, _, _ = run_score(response, count=2)
    by_id = {item.candidate.id: item for item in scores}
    assert by_id["candidate_0"].rejected and not by_id["candidate_1"].rejected
    assert "duplicate rationale catalog ID: 'r'" in by_id["candidate_0"].reasons
    assert all(entry["text"] in by_id["candidate_0"].reasons for entry in catalog[:2])
    restored = CandidateScore.model_validate_json(scores[0].model_dump_json())
    assert [entry.model_dump() for entry in restored.semantic_audit.response_audit.reason_catalog] == catalog


def test_unused_duplicate_catalog_ids_do_not_invalidate_other_decisions():
    response = {"reason_catalog": [{"id": "unused", "text": "First."}, {"id": "unused", "text": "Second."}],
                "scores": [{"candidate_id": "candidate_0", "score": .9, "reasons": ["Independent complete rationale."]}]}
    scores, _, _ = run_score(response, count=1)
    assert not scores[0].rejected
    assert "duplicate rationale catalog ID: 'unused'" in scores[0].semantic_audit.response_audit.validation_errors


def test_accepted_shared_only_decision_expands_every_reference_in_order_without_summarizing():
    long_caveat = "Preserve this exact qualification. " * 100 + "A final unique caveat must survive."
    response = {"reason_catalog": [{"id": "a", "text": long_caveat}, {"id": "b", "text": "Second rationale."}],
                "scores": [{"candidate_id": "candidate_0", "score": .91, "reason_refs": ["b", "a"]}]}
    scores, _, _ = run_score(response, count=1)
    assert not scores[0].rejected
    assert scores[0].reasons[2:] == ["Second rationale.", long_caveat]


def test_duplicate_supplied_ids_keep_both_candidates_and_quarantine_ambiguous_decision():
    candidates, index, profile, compact, _ = scoring_fixture(2)
    candidates[1].id = candidates[0].id
    gateway = LLMGateway(MockLLMClient([{"reason_catalog": compact["reason_catalog"], "scores": compact["scores"][:1]}]),
                         LLMSettings(provider=ProviderName.MOCK))
    scores = AnalysisValueScorer(gateway).score(candidates, index, profile)
    assert len(scores) == 2 and all(item.rejected for item in scores)
    assert {item.candidate.title for item in scores} == {candidate.title for candidate in candidates}
    assert all("duplicate supplied candidate ID" in item.reasons for item in scores)


def test_evidence_rejection_retains_original_positive_model_decision():
    candidates, index, profile, compact, _ = scoring_fixture(1)
    candidates[0].observation_ids = candidates[0].observation_ids[:1]
    gateway = LLMGateway(MockLLMClient([compact]), LLMSettings(provider=ProviderName.MOCK))
    score = AnalysisValueScorer(gateway).score(candidates, index, profile)[0]
    assert score.rejected and "insufficient or low-confidence evidence" in score.reasons
    assert score.semantic_audit.decisions[0].rejected is False
    assert score.semantic_audit.decisions[0].score == .93


def test_prefilter_budget_keeps_every_candidate_and_unrequested_model_decisions_stay_audit_only():
    candidates, index, profile, _, _ = scoring_fixture(164)
    bounded = AnalysisCandidateGenerator._prefilter(candidates, index, profile)
    bounded_ids = {item.id for item in bounded}
    outside = next(item for item in candidates if item.id not in bounded_ids)
    response = {"scores": [
        {"candidate_id": bounded[0].id, "score": .9, "reasons": ["Reviewed supplied candidate."]},
        {"candidate_id": outside.id, "score": 1.0, "reasons": ["This candidate was not supplied for review."]},
    ]}
    client = MockLLMClient([response, {'scores':[]}, {'scores':[]}, {'scores':[]}])
    scores = AnalysisValueScorer(LLMGateway(client, LLMSettings(provider=ProviderName.MOCK))).score(candidates, index, profile)
    assert len(scores) == 164
    assert sum(not item.rejected for item in scores) == 1
    unreviewed = next(item for item in scores if item.candidate.id == outside.id)
    assert unreviewed.rejected and "outside candidate review budget" in unreviewed.reasons
    assert not unreviewed.semantic_audit.decisions
    assert scores[0].semantic_audit.response_audit.unmatched_decisions[0].candidate_id == outside.id
    wire = ast.literal_eval(client.calls[0][1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
    assert len(wire['candidates']) == 160
    assert len(client.calls)==4
    assert all('source_reason_ref' in {**wire.get('candidate_constants', {}), **row} for row in wire['candidates'])


def test_full_pipeline_json_preserves_raw_values_pages_candidates_and_both_decision_layers():
    candidates, index, profile, compact, _ = scoring_fixture(4)
    gateway = LLMGateway(MockLLMClient([compact]), LLMSettings(provider=ProviderName.MOCK))
    scores = AnalysisValueScorer(gateway).score(candidates, index, profile, maximum=1)
    result = PipelineResult(
        document=ParsedDocument(document_id="synthetic", sha256="fixture", safe_filename="fixture.pdf", page_count=3),
        profile=profile, observations=index.observations, candidates=candidates, candidate_scores=scores,
        analysis_plan=AnalysisPlanner().plan(scores, index),
    )
    restored = PipelineResult.model_validate_json(export_json(result))
    assert restored == result
    assert {source.page for observation in restored.observations for source in observation.evidence} == {1, 2, 3}
    assert [observation.raw_value for observation in restored.observations] == ["100.0", "120.0", "150.0"] * 4
    assert all(item.semantic_audit.decisions[0].reason_refs for item in restored.candidate_scores)
    assert len(restored.analysis_plan) == 1
    accepted = next(item for item in restored.candidate_scores if not item.rejected)
    assert accepted.score == pytest.approx(.3 * (.5 * .9 + .3 * 1.0 + .2 * 1.0) + .7 * .93)


def test_legacy_candidate_score_and_semantic_response_caches_remain_readable(tmp_path):
    candidates, _, _, _, legacy = scoring_fixture(1)
    old_score = {"candidate": candidates[0].model_dump(mode="json"), "score": .88, "reasons": ["Legacy reason."], "rejected": False}
    (tmp_path / "old-score.json").write_text(json.dumps(old_score), encoding="utf-8")
    (tmp_path / "old-response.json").write_text(json.dumps(legacy), encoding="utf-8")
    cache = DiskCache(tmp_path)
    score = cache.get_model("old-score", CandidateScore)
    response = cache.get_model("old-response", SemanticCandidateScores)
    assert score.semantic_audit is None and score.reasons == ["Legacy reason."]
    assert response.reason_catalog == [] and response.scores[0].reason_refs == []
    scores, _, _ = run_score(response.model_dump(mode="json"), count=1)
    assert not scores[0].rejected
    assert scores[0].reasons[2:] == legacy["scores"][0]["reasons"]


def test_compact_gateway_cache_reexpands_without_aliasing_or_model_call(tmp_path):
    candidates, index, profile, compact, _ = scoring_fixture(4)
    client = MockLLMClient([compact])
    gateway = LLMGateway(client, LLMSettings(provider=ProviderName.MOCK), cache=DiskCache(tmp_path))
    scorer = AnalysisValueScorer(gateway)
    first = scorer.score(candidates, index, profile)
    expected = deepcopy(first)
    first[0].reasons.append("Mutation must not contaminate cached model output.")
    first[0].semantic_audit.decisions[0].reasons.append("Also isolate original decisions.")
    assert scorer.score(candidates, index, profile) == expected
    assert len(client.calls) == 1 and gateway.usage[-1]["cache_hit"]


@pytest.mark.parametrize("provider", list(ProviderName))
def test_semantic_candidate_scoring_keeps_complex_reasoning_default_for_every_provider(provider):
    policy = request_reasoning_policy(LLMSettings(provider=provider), stage="planner",
                                      operation="SemanticCandidateScores", model="deepseek-flash")
    assert policy["intent"] == "preserve" and policy["options"] == {}


def test_empty_and_no_gateway_scoring_remain_deterministic():
    candidates, index, profile, _, _ = scoring_fixture(4)
    assert AnalysisValueScorer().score([], index, profile) == []
    scores = AnalysisValueScorer().score(candidates, index, profile)
    assert all(item.semantic_audit is None for item in scores)
    assert all(not item.rejected for item in scores)

def test_shared_candidate_fields_restore_every_original_candidate_and_exception():
    from adaptive_document_agent.agent.value_scorer import _scoring_transport
    candidates, _, profile, _, _ = scoring_fixture(40)
    candidates[-1].reason += ' Unique source qualification.'
    before = [c.model_dump(mode='json') for c in candidates]
    wire = _scoring_transport(candidates, profile)
    restored = []
    for row in wire['candidates']:
        row = {**wire.get('candidate_constants', {}), **row}
        if 'observation_refs' in row:
            row['observation_ids'] = [wire['observation_id_catalog'][index]
                                      for index in row.pop('observation_refs')]
        if 'source_reason_ref' in row:
            row['reason'] = wire['source_reason_catalog'][row.pop('source_reason_ref')]
        restored.append(row)
    assert restored == before
    assert [c.model_dump(mode='json') for c in candidates] == before
    assert len(str(wire)) < len(str(_scoring_payload(candidates, profile)))


def test_overlapping_evidence_membership_preserves_exact_ids_duplicates_and_order():
    from adaptive_document_agent.agent.value_scorer import _scoring_transport
    candidates, _, profile, _, _ = scoring_fixture(40)
    ids = [f'observation_{index:064x}' for index in range(11)]
    for index, candidate in enumerate(candidates):
        candidate.observation_ids = [ids[index % 11], ids[(index + 1) % 11], ids[index % 11]]
    before = [candidate.model_dump(mode='json') for candidate in candidates]
    wire = _scoring_transport(candidates, profile)
    assert wire['observation_id_catalog']
    restored = []
    for row in wire['candidates']:
        value = {**wire.get('candidate_constants', {}), **row}
        value['observation_ids'] = [wire['observation_id_catalog'][index]
                                    for index in value.pop('observation_refs')]
        if 'source_reason_ref' in value:
            value['reason'] = wire['source_reason_catalog'][value.pop('source_reason_ref')]
        restored.append(value)
    assert restored == before
    assert [candidate.model_dump(mode='json') for candidate in candidates] == before
    assert len(str(wire)) < len(str(_scoring_payload(candidates, profile))) * .7
