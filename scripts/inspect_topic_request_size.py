"""Measure saved-run topic input transport offline; never request a model verdict."""
import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adaptive_document_agent.agent.coverage_review_context import compact_context, encode
from adaptive_document_agent.agent.presentation_topic_selector import PresentationTopicSelector
from adaptive_document_agent.agent.topic_selection_references import selection_request, reference_input
from adaptive_document_agent.models import PipelineResult


def restore_input(wire, references):
    restored = deepcopy(wire)
    position = restored['series_columns'].index('id')
    for row in restored['all_extracted_series']:
        row[position] = references[row[position]]
    for field in ('ratio_definitions', 'source_row_qualifications'):
        for row in restored.get(field, []):
            row['series_id'] = references[row['series_id']]
    for view in restored.get('same_source_row_period_views', []):
        for row in view['same_source_row']:
            row['series_id'] = references[row['series_id']]
    return restored


class RequestCaptured(Exception):
    pass


class NoModel:
    def generate_structured(self, *args, **kwargs):
        raise RequestCaptured


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('analysis_json', type=Path)
    args = parser.parse_args()
    raw = args.analysis_json.read_bytes()
    result = PipelineResult.model_validate_json(raw)
    metrics = {}

    def capture(payload):
        baseline = encode(compact_context(payload), factor_cells=True)
        encoded, references = selection_request(payload)
        wire, mapping = reference_input(payload)
        assert restore_input(wire, mapping) == payload
        metrics.update(series_count=len(payload['all_extracted_series']),
            original_payload_characters=len(baseline), reference_payload_characters=len(encoded),
            reduction_percent=round(100 * (1 - len(encoded) / len(baseline)), 2),
            reference_count=len(references), all_source_fields_roundtrip=True,
            model_called=False, semantic_approval=False)
        return encoded, references

    with patch('adaptive_document_agent.agent.topic_selection_references.selection_request', capture):
        try:
            PresentationTopicSelector(NoModel()).select(result)
        except RequestCaptured:
            pass
    metrics['source_file_unchanged'] = sha256(raw).digest() == sha256(args.analysis_json.read_bytes()).digest()
    print(json.dumps(metrics, indent=2))


if __name__ == '__main__':
    main()
