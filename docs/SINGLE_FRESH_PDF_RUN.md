# Single-invocation analysis from the original PDF

The fresh live driver now reads only the original PDF. It neither loads a
checkpoint nor supplies saved analysis to `DocumentOrchestrator.analyse_pdf`.
The orchestrator is called once with `resume=None`, without a request cache.
Diagnostics record `checkpoint: null`, `resume_supplied: false`, and
`request_cache_enabled: false` so a reporting continuation cannot be mistaken
for a new extraction run.

## Bounded corrections within the same invocation

An introductory source read with an overflowing fact list uses its existing
single format-correction allowance to consolidate only the invalid lists.
The model receives the complete original source and all original facts.
Python freezes ownership ranges, roles, titles, reading notes and unaffected
parts. Correction fields are required and nonempty; missing output cannot
silently clear a list. Literal source binding and independent editorial review
still follow. Truncated/refused responses, malformed envelopes and other schema
errors do not gain this correction route.

Final publication review can make at most two addressed copy corrections in
the same live invocation. Each correction requires a fresh, exact-context
independent source verdict identifying rejected pages with accepted omission
coverage. It preserves accepted siblings, numeric inputs, raw source data and
the selected findings. A copy correction cannot settle a missing finding or
reuse a consumed/stale verdict. Every merge reruns source/audit validation,
actual native page-budget measurement and full independent publication review.
No checkpoint file is created and reloaded to perform those corrections.

When a completed copy patch uses native quantity-reference arrays, the exact
source strings are restored before measuring its text length. An overflowing
restored string can use the existing single copy-capacity correction. Other
fields and successful sibling patches remain frozen. Valid partial sibling
patches remain available to the meaning-correction step, but an incomplete
patch does not gain another source-correction request.

Checked ruled-table headers now preserve an isolated literal assurance marker
on its exact period column before observations are created. Reference columns
such as Notes are excluded from period-anchor matching. Independent coordinate
verification handles headers inside a ruled grid's bounding box. Grouped,
unchecked, conflicting and unmarked cells remain unknown; the raw grid and
original evidence are unchanged.

## One explicit time budget

`ANALYSIS_TIMEOUT_SECONDS` configures a single monotonic clock shared by
ingestion, all workers, queue admission, provider retries, corrections and
report review. The default remains 900 seconds. Valid values are 60–7200;
NaN, infinity and invalid/out-of-range settings are rejected. An existing
clock is never reset between phases. Exceptions, partial diagnostics and UI
labels report the actual configured duration.

For a large source-rich PDF with real model reviews, the verification run uses
an explicit 2700-second (45-minute) budget. This changes the spending limit,
not the model's source/semantic reasoning or any publication gate.

Example (supply the configured local renderer paths when needed):

```powershell
python -m scripts.run_live_checkpoint --fresh --pdf input.pdf --env .env --provider openai --model gpt-6-luna --analysis-timeout-seconds 2700 --output output/fresh-run --export-pptx --render-node <node.exe> --render-module <artifact_tool.mjs>
```

There is deliberately no `--checkpoint` argument in the fresh command.
Reporting continuation remains a separate explicit operation.

## Validation

- 43 targeted source-reading, deadline and local-copy checks passed.
- 917 affected reporting/summary/selection tests passed; 23 optional skips.
- The complete regression run, including the column-binding fix, passed 7065
  tests, with 39 optional skips (547.52 seconds). The column-binding change also
  passed 79 targeted extraction and assurance checks.
- Fresh-driver tests prove a nonexistent checkpoint is never opened and the
  original PDF is passed to the orchestrator exactly once with `resume=None`.
- Live-copy tests require a new independent verdict after each correction,
  enforce the two-edit bound and prevent omission approval through copy edits.

## Real original-PDF verification

On 2026-11-12 a new `live_fresh_pdf` invocation completed analysis and exported
the presentation in 1041.434 seconds (17 minutes 21 seconds). It started from
the original 524-page PDF, made 93 real OpenAI `gpt-6-luna` calls and retained
1539 observations and 20 deterministic analysis results. Its diagnostics show
`checkpoint: null`, `resume_supplied: false`, and
`request_cache_enabled: false`. The explicitly configured shared analysis
budget was 2700 seconds; this result does not claim completion within the
unchanged 900-second default.

The exported file has 20 physical slides, five editable native charts and five
embedded chart workbooks. The normal export gates ran without `force`, passed
on the first rendered QA attempt, reported `facts_preserved: true`, and required
no export repair. Microsoft PowerPoint opened the file and rendered all 20
pages; every page was visually inspected for clipping, overlap and readable
source footers. The final PPTX SHA-256 is
`a7c0c73c0056bbc685d5021ad02c8c65819ce19b8bc0466cdadcfe4657aeae42`.

Private run diagnostics, the source PDF and the exported presentation remain
outside the committed source tree. Local verification artifacts are under
the ignored `output/single-fresh-20261112-03/` directory.

Two earlier fresh attempts exposed separate terminal failures, rather than
timeouts: restored quantity text exceeded its copy limit (1279.546 seconds,
84 real model calls), then a ruled-header assurance marker was missing from its
observation (595.796 seconds, 65 real model calls). Neither attempt was resumed
to verify this change. Each verification attempt starts again from the PDF.
