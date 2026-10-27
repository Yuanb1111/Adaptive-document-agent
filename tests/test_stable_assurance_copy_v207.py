"""Localization and export in different processes must see the same copy."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize('with_charts', [False, True])
def test_context_copy_is_stable_across_hash_seeds(with_charts):
    script = r'''
import json
from types import SimpleNamespace
from adaptive_document_agent.models import ChartPlan
from adaptive_document_agent.document_model.index import DocumentIndex
from adaptive_document_agent.services.presentation_context_notes import slide_context_notes
from adaptive_document_agent.agent import report_audit_scope
from tests.test_report_audit_scope_v174 import fixture

result, binding = fixture()
amount = result.observations[0]
result.observations = [amount.model_copy(update={'id': 'measure_'+str(i),
    'metric_original': 'Measure '+str(i), 'metric_canonical': None}) for i in range(8)]
quote = SimpleNamespace(page=5)
report_audit_scope.reviewed_audit_bindings = lambda _: {
    o.id: SimpleNamespace(status='audited', value_quote=quote, scope_evidence=[quote])
    for o in result.observations}
slide = result.presentation_plan.slides[0]
slide.observation_ids = [o.id for o in result.observations]
slide.theme_id = None
charts = [ChartPlan(id='chart', title='Measures', chart_type='bar', question='What is reported?',
    observation_ids=slide.observation_ids)] if WITH_CHARTS else []
print(json.dumps(slide_context_notes(result, slide, charts, DocumentIndex(result.observations), definitions=[])))
'''.replace('WITH_CHARTS', repr(with_charts))
    outputs = [subprocess.run([sys.executable, '-c', script],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, 'PYTHONHASHSEED': str(seed)}, capture_output=True,
        text=True, check=True, timeout=45).stdout for seed in (1, 17, 200)]
    assert outputs[0] == outputs[1] == outputs[2]
    assert 'Measure 0, Measure 1, Measure 2' in outputs[0]
