"""The offline CLI discloses both response-capacity wins and input-cost countercases."""
import json
from pathlib import Path
import subprocess
import sys


def test_candidate_capacity_cli_keeps_all_outcomes_and_reports_attempt_tradeoffs():
    repo = Path(__file__).resolve().parents[1]
    completed = subprocess.run([sys.executable, '-m', 'scripts.benchmark_candidate_capacity'],
        cwd=repo, capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report['network_calls'] == 0 and report['provider_token_usage'] is None
    expected_attempts = {'verbose_all_over_20': (12, 8), 'no_truncation': (4, 8),
                         'sparse_last_parent_and_child': (8, 10)}
    for name, scenario in report['scenarios'].items():
        before, after = scenario['baseline_40'], scenario['current_20']
        assert scenario['identical_outcomes']
        assert (before['physical_attempts'], after['physical_attempts']) == expected_attempts[name]
        assert before['candidate_count'] == after['candidate_count'] == 160
        for result in (before, after):
            assert result['scoring_worker_budget'] == 3 and result['source_unchanged']
            assert result['every_candidate_completed_once'] and result['every_decision_and_reason_valid']
            assert result['failure_audit_count'] == result['truncated_attempts']
    assert report['scenarios']['verbose_all_over_20']['request_character_delta'] < 0
    assert report['scenarios']['no_truncation']['request_character_delta'] > 0
    assert report['scenarios']['sparse_last_parent_and_child']['request_character_delta'] > 0
