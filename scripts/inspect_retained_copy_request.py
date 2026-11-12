"""Compare full and local retained-review requests offline, without model approval.

Run: python -m scripts.inspect_retained_copy_request analysis.json
"""
import argparse
import json
from pathlib import Path
from types import SimpleNamespace

from adaptive_document_agent.models import PipelineResult
from adaptive_document_agent.agent.retained_analysis import (
    RetainedAnalysisSelection, selected_record, selection_context,
)
from adaptive_document_agent.agent.retained_selection_coverage import review_selection_coverage
from adaptive_document_agent.utils.record_encoding import decode_records


def inspect(path):
    result = PipelineResult.model_validate_json(Path(path).read_bytes())
    selection = RetainedAnalysisSelection.model_validate(selected_record(result)['selection'])
    context = selection_context(result)
    latest = next(json.loads(w.message) for w in reversed(result.validation_warnings)
        if w.code == 'retained_selection_coverage' and json.loads(w.message).get('copy_review_ids'))

    class Capture:
        calls = []

        def generate_structured(self, messages, schema, **kwargs):
            self.calls.append(messages)
            # Protocol fixture only. It never reaches the publication gate.
            return schema(accepted=True, reason='Offline request measurement only.')

    capture = Capture()
    review_selection_coverage(capture, context, selection, result)
    review_selection_coverage(capture, {**context, 'copy_review_ids': latest['copy_review_ids']}, selection, result)
    wires = [call[-1]['content'] for call in capture.calls]
    packets = [decode_records(json.loads(wire.split('\n', 1)[1].rsplit('\n', 1)[0])) for wire in wires]
    assert packets[0]['source_pages'] == packets[1]['source_pages']
    settings = SimpleNamespace(presentation_strategy='retained_analysis')
    from adaptive_document_agent.agent.brief_reporting_resume import retained_brief_reporting
    current = PipelineResult(document=result.document.model_copy(deep=True),
        profile=result.profile.model_copy(deep=True), observations=result.observations,
        analysis_plan=result.analysis_plan, analysis_results=result.analysis_results)
    class Probe:
        def generate_structured(self, *args, **kwargs):
            from adaptive_document_agent.services.llm.exceptions import LLMResponseError
            raise LLMResponseError('Offline inspection stops before model-owned copy repair.')

    probe = Probe()
    probe.settings = settings
    resumed = retained_brief_reporting(result, current, probe)
    return dict(full_request_chars=len(wires[0]), copy_request_chars=len(wires[1]),
        reduction_percent=round(100 * (1 - len(wires[1]) / len(wires[0])), 1),
        full_findings=len(packets[0]['findings']), copy_findings=len(packets[1]['findings']),
        source_pages_preserved=[p['page'] for p in packets[1]['source_pages']],
        timeout_reporting_reusable=resumed is not None,
        timeout_copy_repair_required=resumed is not None and resumed.failed_stage == 'presentation_selection',
        model_calls=0,
        publication_approved=False, end_to_end_verified=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('analysis_json')
    args = parser.parse_args()
    print(json.dumps(inspect(args.analysis_json), indent=2))
