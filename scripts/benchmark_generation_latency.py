"""Offline, same-input checks for generation request volume and scheduling.

Run against two worktrees with --repo. No credentials or live model calls.
The shared synthetic harness runs the actual orchestrator, including the older
baseline's existing introduction/slide-planning overlap. Fixed 10ms request
stubs exercise wiring only; separately disclosed scheduling delays demonstrate
concurrency, not live-provider end-to-end performance.
"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
from statistics import median
import sys
from time import perf_counter, sleep
from types import SimpleNamespace


def lexical_units(text):
    """A deterministic text counter, never a provider tokenizer/billing count."""
    return len(re.findall(r"\w+|[^\w\s]", text))


def run(args):
    # Import the selected revision in a fresh process; never mix app modules
    # from the baseline and current checkout in one interpreter.
    sys.path.insert(0, str(Path(args.repo).resolve()))
    from pydantic import BaseModel
    from adaptive_document_agent.agent.company_introduction import IntroductionPages
    from adaptive_document_agent.agent.executive_brief import BriefSourcePages, ExecutiveBriefWriter
    from adaptive_document_agent.agent.value_scorer import AnalysisValueScorer
    from adaptive_document_agent.document_model import DocumentIndex
    from adaptive_document_agent.models import (
        AnalysisCandidate, DocumentPage, DocumentProfile, Observation, ParsedDocument, PipelineResult, SourceEvidence,
    )
    from adaptive_document_agent.models.executive_brief import ExecutiveBrief
    from adaptive_document_agent.services.llm import LLMGateway, LLMSettings
    from adaptive_document_agent.services.llm.litellm_provider import LiteLLMProvider

    class ReplayProvider(LiteLLMProvider):
        """Intercept every transport request; no real-provider fallback exists."""

        def __init__(self, answers):
            super().__init__(LLMSettings(model="deepseek-flash"))
            self.answers = iter(answers)
            self.requests = []

        def _completion(self, messages, **kwargs):
            value = next(self.answers)
            if callable(value):
                value = value(messages, kwargs)
            content = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            request = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
            sleep(.01)  # Do not assume reasoning-token throughput or provider speed.
            self.requests.append({
                "request_chars": len(request), "response_chars": len(content),
                "thinking": kwargs.get("extra_body"),
                "input_lexical_units": lexical_units(request),
                "output_lexical_units": lexical_units(content),
                "provider_token_usage": None,
            })
            return SimpleNamespace(
                model="synthetic-replay", usage=None,
                choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason="stop")],
            )

    def measured(function, answers):
        provider = ReplayProvider(answers)
        gateway = LLMGateway(provider, provider.settings, cache_enabled=False)
        started = perf_counter()
        result = function(gateway)
        return {
            "wall_ms": round((perf_counter() - started) * 1000, 2),
            "calls": len(provider.requests), "requests": provider.requests,
            "operations": [row["operation"] for row in gateway.usage],
            "result": result.model_dump(mode="json") if hasattr(result, "model_dump") else result,
        }

    class ComplexAnalysis(BaseModel):
        decision: str

    def reasoning(gateway):
        return [
            gateway.generate_structured([], IntroductionPages, stage="presentation").model_dump(),
            gateway.generate_structured([], BriefSourcePages, stage="report").model_dump(),
            gateway.generate_structured([], ComplexAnalysis, stage="planner").model_dump(),
        ]

    output = {
        "fixture_scope": "Synthetic fixtures only; no user files, credentials, network or paid models",
        "mode": "synthetic_offline_replay",
        "token_definition": "Provider token usage unavailable offline; lexical units are not model tokens",
        "timing_definition": "Measured wall time under fixed 10ms request stubs; not live generation latency",
    }
    output["reasoning"] = measured(reasoning, [
        {"pages": [1, 2]}, {"pages": [1, 2]}, {"decision": "Preserve complex reasoning."},
    ])

    texts = [f"Service queue {letter} reported {10+i} units during 2025." for i, letter in enumerate("ABCDEF")]
    result = PipelineResult(
        document=ParsedDocument(
            document_id="synthetic", sha256="synthetic", safe_filename="fixture.pdf", page_count=6,
            pages=[DocumentPage(page_number=i+1, text=text) for i, text in enumerate(texts)],
        ), profile=DocumentProfile(),
    )
    good = {"title": "Key takeaways", "items": [
        {"label": f"Queue {letter}", "text": text, "evidence": [{"page": i+1, "text": text}]}
        for i, (letter, text) in enumerate(zip("ABCDEF", texts))
    ]}
    bad = json.loads(json.dumps(good))
    bad["items"][-1]["text"] = bad["items"][-1]["text"].replace("15", "999")

    def repair_response(messages, options):
        schema = json.loads(messages[0]["content"].split("schema: ", 1)[1])
        if schema["title"] == "ExecutiveBrief":
            return good
        answer = {}
        for name in schema["properties"]:
            if name.startswith("item_"):
                answer[name] = good["items"][int(name.split("_")[-1])]
            elif name == "title":
                answer[name] = good["title"]
            elif name == "additions":
                answer[name] = []
            else:
                raise AssertionError("Unexpected repair schema " + name)
        return answer

    output["brief"] = measured(lambda gateway: ExecutiveBriefWriter(gateway).generate(result), [bad, repair_response])
    # Compare the complete model output using the measured revision's defaults.
    # Keep replay responses unchanged so old/new request-volume comparisons use
    # identical fixtures; no returned facts or evidence are excluded from checks.
    expected_brief = ExecutiveBrief.model_validate(good).model_dump(mode="json")
    assert output["brief"]["result"] == expected_brief

    fixture_path = Path(__file__).resolve().parents[1] / "tests/fixtures/candidate_scoring_rationales.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    reason_catalog = {entry["id"]: entry["text"] for entry in fixture["reason_catalog"]}
    observations, candidates, compact_decisions, legacy_scores = [], [], [], []
    for position in range(40):
        case = fixture["cases"][position % len(fixture["cases"])]
        metric = f"{case['metric']} {position}"
        identifiers = [f"observation-{position}-{year}" for year in (2023, 2024, 2025)]
        candidates.append(AnalysisCandidate(
            id=f"candidate_{position}", title=f"Compare {metric}", metric=metric,
            analysis_type=case["analysis_type"], dimensions=["region"],
            observation_ids=identifiers, reason=fixture["source_reason"],
        ))
        for page, (identifier, year, value) in enumerate(zip(identifiers, (2023, 2024, 2025), (100, 120, 150)), 1):
            observations.append(Observation(
                id=identifier, metric_original=metric, value=value, raw_value=f"{value}.0",
                unit="source units", period=str(year), dimensions={"region": "Remote"}, confidence=.9,
                evidence=[SourceEvidence(page=page, text=f"{metric}: {value}.0 ({year})",
                                         table_id=f"table-{position}", extraction_method="digital_table", confidence=.9)],
            ))
        decision = {
            "candidate_id": candidates[-1].id, "score": case["score"], "rejected": case["rejected"],
            "reason_refs": case["reason_refs"],
            "reasons": [*case["reasons"], f"Review specifically covers {', '.join(identifiers)}."],
        }
        compact_decisions.append(decision)
        legacy_scores.append({
            **{key: value for key, value in decision.items() if key != "reason_refs"},
            "reasons": [*(reason_catalog[ref] for ref in decision["reason_refs"]), *decision["reasons"]],
        })

    def score_response(messages, options):
        schema = json.loads(messages[0]["content"].split("schema: ", 1)[1])
        if "reason_catalog" not in schema["properties"]:
            return {"scores": legacy_scores}
        catalog = reason_catalog
        # The production list representation preserves duplicate IDs for audit;
        # the transitional dict branch also lets this runner inspect older worktrees.
        if schema["properties"]["reason_catalog"].get("type") == "array":
            catalog = [{"id": key, "text": value} for key, value in catalog.items()]
        return {
            "reason_catalog": catalog,
            "scores": compact_decisions,
        }

    def score_run(gateway):
        scores = AnalysisValueScorer(gateway).score(
            candidates, DocumentIndex(observations),
            DocumentProfile(document_type="Unfamiliar mixed evidence report", document_purpose="Compare measured outcomes",
                            metrics=[candidate.metric for candidate in candidates]), maximum=12,
        )
        return [item.model_dump(mode="json", include={"candidate", "score", "reasons", "rejected"}) for item in scores]

    output["scoring"] = measured(score_run, [score_response])
    output["schedule"] = scheduling(args.harness, args.repeats)
    return output


def scheduling(harness_path, repeats):
    """Run real orchestration with controlled independent work and source snapshots."""
    import pytest

    spec = importlib.util.spec_from_file_location("latency_harness", harness_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    delays = {"IntroductionPages": .07, "IntroductionDraft": .05,
              "candidate_scoring": .04, "reporting": .06, "slide_plan": .02}
    samples = []
    for _ in range(repeats):
        with pytest.MonkeyPatch.context() as patch:
            harness = module.configure_pipeline(patch, delays=delays)
            started = perf_counter()
            result = harness.run()
            elapsed = (perf_counter() - started) * 1000
            projection = result.model_dump(mode="json", include={
                "document", "profile", "observations", "analysis_results", "presentation_plan",
            })
            checksum = hashlib.sha256(json.dumps(projection, sort_keys=True).encode()).hexdigest()
            intervals = [
                {"name": row["name"], "started_ms": round((row["started"]-started)*1000, 3),
                 "finished_ms": round((row["finished"]-started)*1000, 3)}
                for row in harness.intervals
            ]
            samples.append({
                "wall_ms": round(elapsed, 3), "stage_timings_ms": result.timings_ms,
                "stage_details_ms": result.stage_details_ms,
                "introduction_calls": len(harness.client.operations), "intervals": intervals,
                "output_sha256": checksum,
                "token_usage": "Not supplied by this scheduling stub; not zero.",
            })
    assert len({sample["output_sha256"] for sample in samples}) == 1
    assert all(sample["introduction_calls"] == 2 for sample in samples)
    return {"stub_delays_seconds": delays, "measured_runs": repeats,
            "median_wall_ms": round(median(sample["wall_ms"] for sample in samples), 3), "runs": samples}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="Worktree whose production code is measured")
    parser.add_argument("--harness", default=str(Path(__file__).resolve().parents[1] / "tests/test_early_company_introduction.py"))
    parser.add_argument("--repeats", type=int, default=10)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    print(json.dumps(run(args), indent=2))


if __name__ == "__main__":
    main()
