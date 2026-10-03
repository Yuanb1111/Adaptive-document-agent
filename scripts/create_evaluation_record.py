"""Create a privacy-safe evaluation record from an analysis_data JSON export."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adaptive_document_agent.models import PipelineResult
from adaptive_document_agent.services.evaluation_records import build_evaluation_record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("analysis_json", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--dataset-role", required=True, choices=("fix_sample", "holdout"))
    parser.add_argument("--run-mode", required=True, choices=("first_run", "cached_run"))
    parser.add_argument("--code-version")
    args = parser.parse_args()
    version = args.code_version or subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True, encoding="utf-8").strip()
    payload = json.loads(args.analysis_json.read_text(encoding="utf-8"))
    payload.pop("llm_cost_summary", None)
    result = PipelineResult.model_validate(payload)
    record = build_evaluation_record(result, code_version=version,
                                     dataset_role=args.dataset_role, run_mode=args.run_mode)
    args.output.write_text(record.model_dump_json(indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
