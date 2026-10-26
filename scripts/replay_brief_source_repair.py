"""Replay a recorded source patch in place without provider calls or meaning approval."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adaptive_document_agent.models import PipelineResult
from adaptive_document_agent.models.executive_brief import ExecutiveBrief
from adaptive_document_agent.agent.brief_source_repair import correct_residual_source_errors
from adaptive_document_agent.services.executive_brief import validate_executive_brief


def replay(path):
    raw = json.loads(Path(path).read_text(encoding='utf-8'))
    audit = json.loads(next(row['message'] for row in reversed(raw['validation_warnings'])
        if row['code'] == 'executive_brief_repair_audit'))
    result = PipelineResult.model_validate(raw)
    before_document = result.document.model_dump_json()
    before_observations = [row.model_dump_json() for row in result.observations]
    patch = audit['patch']
    items = [patch.get(f'item_{index}', item) for index, item in enumerate(audit['original']['items'])]
    items.extend(patch.get('additions', []))
    brief = ExecutiveBrief.model_validate(dict(title=patch.get('title', audit['original']['title']), items=items))
    original = brief.model_dump_json()
    class RecordedGateway:
        def generate_structured(self, messages, schema, **kwargs):
            return schema.model_validate(audit['residual_source_correction']['proposal'])
    record = {}
    revised = correct_residual_source_errors(RecordedGateway(), brief, result=result,
        excerpts={page.page_number: page.text for page in result.document.pages},
        initial_errors=audit['initial_errors'], audit=record)
    assert result.document.model_dump_json() == before_document
    assert [row.model_dump_json() for row in result.observations] == before_observations
    assert brief.model_dump_json() == original
    details = record.get('residual_source_correction', {})
    return dict(pipeline_version=raw['pipeline_version'], status=details.get('status', 'not_attempted'),
        recorded_accepted_indices=audit['residual_source_correction'].get('accepted_indices', []),
        replay_accepted_indices=details.get('accepted_indices', []),
        remaining_source_errors=validate_executive_brief(revised or brief, result),
        source_data_unchanged=True, model_calls=0, semantic_approval=False, end_to_end_verified=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path)
    print(json.dumps(replay(parser.parse_args().path), ensure_ascii=False, indent=2))
