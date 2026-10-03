import json

from adaptive_document_agent.services.evaluation_records import ExportOutcome, build_evaluation_record
from tests.test_executive_brief import result_for


def test_evaluation_record_separates_cohort_run_mode_and_redacts_content() -> None:
    result = result_for(["Private source content 12."])
    result.pipeline_version = "v78"
    result.timings_ms = {"discovery": 120}
    result.pipeline_total_ms = 250
    result.llm_usage = [{
        "stage": "discovery", "operation": "ChunkDiscovery", "provider": "mock", "model": "mock-1",
        "status": "app_cache_hit", "cache_hit": True, "api_key": "secret", "prompt": "private text",
    }]
    record = build_evaluation_record(
        result, code_version="abc123", dataset_role="fix_sample", run_mode="cached_run",
        exports=[ExportOutcome(format="pptx", success=False, failure_reason="render unavailable")],
        notes=["Synthetic only; real-file verification pending."],
    )
    payload = json.loads(record.model_dump_json())
    assert payload["file_id"] == "a" * 64
    assert payload["dataset_role"] == "fix_sample" and payload["run_mode"] == "cached_run"
    assert payload["cache_hits"] == {"discovery": 1}
    assert payload["stage_timings_ms"] == {"discovery": 120}
    assert payload["exports"][0]["failure_reason"] == "render unavailable"
    assert "secret" not in record.model_dump_json() and "Private source" not in record.model_dump_json()


def test_evaluation_record_does_not_invent_export_or_real_file_results() -> None:
    record = build_evaluation_record(result_for(["Synthetic evidence."]), code_version="abc123",
                                     dataset_role="holdout", run_mode="first_run")
    assert record.exports == []
    assert record.real_file_verified is False
