"""Exercise the CI benchmark entry point with offline production-code replay."""

import json
from pathlib import Path
import subprocess
import sys


def test_generation_latency_cli_preserves_repaired_evidence_and_repeatable_outputs():
    repo = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, "-m", "scripts.benchmark_generation_latency",
         "--repo", str(repo), "--repeats", "2"],
        cwd=repo, capture_output=True, text=True, timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["mode"] == "synthetic_offline_replay"
    brief = report["brief"]
    assert brief["calls"] == 2
    assert brief["operations"] == ["ExecutiveBrief", "ExecutiveBriefPatch"]
    assert brief["result"] == {"title": "Key takeaways", "items": [
        {"label": f"Queue {letter}",
         "text": f"Service queue {letter} reported {10 + index} units during 2025.",
         "evidence": [{"page": index + 1,
                       "text": f"Service queue {letter} reported {10 + index} units during 2025."}],
         "quantity_representations": [], "comparison_table": None}
        for index, letter in enumerate("ABCDEF")
    ]}
    for component in ("reasoning", "brief", "scoring"):
        assert all(request["provider_token_usage"] is None
                   for request in report[component]["requests"])
    schedule = report["schedule"]
    assert schedule["measured_runs"] == len(schedule["runs"]) == 2
    assert len({run["output_sha256"] for run in schedule["runs"]}) == 1
    assert all(run["introduction_calls"] == 2 for run in schedule["runs"])
