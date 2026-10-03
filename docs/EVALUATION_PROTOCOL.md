# Lightweight evaluation protocol

This protocol records reproducible engineering evidence without calling a paid model or exposing source documents.

## Cohorts and runs

- Mark every file as either `fix_sample` (used while diagnosing or tuning) or `holdout` (not inspected or used during debugging). Never report the fix sample as holdout performance.
- Record separate `first_run` and `cached_run` executions. Do not compare a cached duration with an uncached baseline as if it were a code speed-up.
- Identify files only by SHA-256. Do not commit source filenames, document text, API keys, or private attachments.
- Record the exact Git commit, pipeline version, provider/model settings, application cache hits, stage and total timings, and every attempted export's success or sanitized failure reason.
- A synthetic run is not a real-file validation. Keep `real_file_verified=false` until the corresponding source JSON and PPT have been matched and reviewed.

Create a machine-readable skeleton from an existing `analysis_data.json`:

```bash
python scripts/create_evaluation_record.py analysis_data.json run-record.json \
  --dataset-role fix_sample --run-mode first_run
```

The command reads existing metadata only; it does not invoke a model. Add export outcomes through the `ExportOutcome` API after actual export attempts.

## Human review template

Copy this table once per file and run mode. Leave scores blank rather than estimating them.

| Field | Entry |
|---|---|
| Record ID / date | |
| File SHA-256 | |
| Cohort (`fix_sample` / `holdout`) | |
| Run (`first_run` / `cached_run`) | |
| Git commit / pipeline version | |
| Model, provider, reasoning/temperature settings | |
| Cache hits by stage | |
| Stage timings / total time | |
| Export success; failure reason | |
| Source JSON and PPT confirmed as same run? | Pending / Yes / No |
| Real source file reviewed? | Pending / Yes / No |
| Key-number accuracy (correct / checked) | |
| Unit accuracy (correct / checked) | |
| Period accuracy (correct / checked) | |
| Material omissions (count and description) | |
| Analysis support (unsupported claims / checked claims) | |
| Practical usefulness (reviewer rubric and rationale) | |
| Human editing time (minutes) | |
| Reviewer notes | |

Accuracy denominators must include every reviewed key claim, including failures. Describe the reviewer rubric before scoring usefulness. Record elapsed human editing time rather than guessing. Do not invent scores when reviewers or original files are unavailable.

## Current validation status

The reported v78 private attachment and its 30-page PPT were unavailable during implementation. Their correspondence, page-level symptoms, business quality, and real-world speed remain **pending**. Synthetic regression tests exercise only the stated failure shapes.
