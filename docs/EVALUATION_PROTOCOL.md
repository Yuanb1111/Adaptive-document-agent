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

## Source-first business acceptance

Before generating a holdout output, prepare a source checklist with physical PDF
pages, the expected fact, its materiality, and the decision affected by omission.
Lock its SHA-256 and UTC timestamp. Do not send this checklist to the generation
model. Read the source independently of the generated topics. Compare source
hashes with available debugging history and disclose the scope of that check.

Use a fixed commit and explicit model settings. Preserve failed attempts. An
authentication failure is an environment failure, not a measured business error.
After a sample informs a code change, treat it as a regression sample and reserve
new holdouts for subsequent acceptance.

The offline `scripts/business_acceptance_report.py` tool reads a local cohort
manifest, locked source checklists, run receipts and explicit output reviews. It
does not invoke an LLM. Source documents, checklists and completed reviews belong
in ignored local output directories, not in Git.

```bash
python scripts/business_acceptance_report.py output/pilot/cohort.json
```

The report separates export results, business review and measured editing time.
Known factual errors fail the fact gate immediately. Without a known failure,
the gate stays pending while important source sections or output claims are
unreviewed, source/output correspondence is unverified, or accuracy denominators
are zero. A material omission fails the gate unless the output specifically
discloses both the missing content and its decision impact. A general disclaimer
does not satisfy this requirement. Record output locators for reviewed claims and
disclosures. Retain failures in every relevant accuracy denominator.
Record SHA-256 for the reviewed `analysis.json` and `presentation.pptx` in
`reviewed_artifacts`; replacing either file invalidates that correspondence.
Count erroneous checklist items separately from failed dimension checks, so one
fact with several mistakes is not reported as several independent errors.
Review important claims introduced by the output even if they are absent from
the source-first checklist. Put those assertions in `additional_claims` with
distinct IDs, original physical pages, output locators and dimension counts.
Their mistakes must enter the relevant accuracy denominators. The declared
`additional_claim_errors` count must match those reviewed assertions; an error
total without its accuracy checks cannot establish complete review.

The reviewer-authored minimum checklist does not establish complete document
coverage. Complete the broader source and output review before setting the
corresponding flags. A Codex review must not be described as an independent human
review, and measured editing time must not be inferred from model runtime.

## Current validation status

The earlier v78 attachment review remained pending when this protocol was first
written. The six-file v88 pilot now failed its scoped business gate; see the
[anonymized baseline](BUSINESS_ACCEPTANCE_BASELINE.md). Its full source/output
review and human editing-time measurement remain incomplete. Local v89 repairs
and regression tests are engineering evidence; they do not establish independent
business acceptance or a successful cloud retest. Source-specific findings and
artifact hashes remain in the ignored local report.
