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

The current performance requirement is completion within 900 seconds, including
PPTX export and rendered QA. The fresh driver checks the same deadline before
and after export: an artifact finishing after that boundary cannot be reported
as a complete successful run. The earlier 2700-second baseline below did not
meet this performance requirement.

Example (supply the configured local renderer paths when needed):

```powershell
python -m scripts.run_live_checkpoint --fresh --pdf input.pdf --env .env --provider openai --model gpt-6-luna --workers 8 --brief-findings 3 --analysis-timeout-seconds 900 --output output/fresh-run --export-pptx --render-node <node.exe> --render-module <artifact_tool.mjs>
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

## Performance changes for the 15-minute requirement

- The gateway supports 1–8 shared cloud request slots, still serial for local
  or stateful clients. `--workers 8` is an explicit verification setting; the
  application can use the same setting through `LLM_DISCOVERY_WORKERS=8`.
- When an independent coverage model gives a complete replacement priority
  list, the existing bounded correction authors only new, removed or flagged
  decisions. Unchanged decisions and page copy stay frozen. The complete merged
  selection still receives fresh source and independent coverage validation.
- A final analytical-page review can overlap supplementary briefing work on an
  isolated snapshot. Its verdict attaches only if its full original context
  fingerprint still matches after source integration and budget preparation.
  Source, observation, chart, analysis or audience-scope changes invalidate it.
  Audience-dependent physical selections remain serial. Rejected current-context
  verdicts use the existing two-edit correction bound without repeating their
  first review. All background work is drained before the invocation ends.
- Lossless record tables factor identical field values into explicit inherited
  constants. Nulls, raw values, signs, source geometry, JSON types and repeated
  row counts are retained; decoding must restore the full original payload.
- Three independent localization batches may overlap under the shared gateway
  admission limit; every translation still receives its independent review.
- In the eight-slot mode, independent owned-item literal reviews may overlap.
  The separate whole-brief context gate still reads every shared source block.
  Workers return unapproved verdicts; only the caller validates source bindings,
  arithmetic and blind audience direction, merges context errors and checkpoints.
  A context rejection or unavailable literal verdict still blocks publication.
- Mixed native-quantity-array and plain-string item patches are partitioned even
  with only two editable items. Each request receives its own exact schema and
  item-owned quantity catalog; it cannot borrow a sibling's reference IDs.
- `--brief-findings 3` explicitly limits initial synthesis to three material
  findings, preserving independent supplementary capacity and all detailed
  analysis pages. The app setting is `LLM_BRIEF_INITIAL_FINDINGS=3`; the legacy
  default capacity remains seven before supplementary reservation.
- Explicit computed cumulative-change labels bind to exact Python calculation
  kind, metric, period pair, sign and rounding. Multiple reported CAGRs in one
  sentence need unique adjacent rate/interval bindings. Levels, mismatched
  intervals and annualized rates cannot borrow cumulative changes.
- After the existing source reread, a fact-free layout record exactly one line
  past the source may be quarantined only if every real line already has exactly
  one owner. Its raw record stays in the audit. Gaps, overlaps, unknown blocks,
  substantive parts and crossing/outlying ranges remain errors.
- The eight-slot introduction route adds a separate source-entailment verdict
  after audience selection is accepted. Unsupported stronger assertions in the
  central-meaning inventory must be corrected through the existing bounded
  meaning-repair path before audience authoring. A source bound or top-N
  membership cannot become an exact value or ordinal merely because an earlier
  relevance reviewer accepted it.

The earlier performance revision passed 7109 full regression checks (39 optional
skips), with 76 further checks for terminal-layout ownership. The subsequent
briefing/gateway regression passed 911 checks (two optional skips), and the latest
source-entailment change passed 63 targeted introduction checks.

At the user's request, work stopped after committing and pushing this revision.
Four fresh 900-second attempts ended at validation gates without producing a
PPTX; none was resumed to claim success. The last attempt exposed a central-meaning
inventory that strengthened a source ranking bound. The new source-entailment
gate addresses that defect but has not yet been verified in another real-model
run. Completion within 15 minutes remains unverified. The older successful
17-minute baseline below does not satisfy the current performance requirement.

## Earlier real original-PDF baseline (over 15 minutes)

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


## 2026-11-13 paused development checkpoint

This checkpoint preserves the current source-authoring and validation repairs;
it is not a verified 15-minute completion. Fresh runs continue to start from
the original PDF with real OpenAI `gpt-6-luna`, cache disabled and no supplied
checkpoint. The latest attempt stopped at source-selection validation after
368.162 seconds and 82 model calls, before PowerPoint export. It produced no
qualifying PPTX.

The changes separate model-owned priority selection, source-page authoring and
independent owned-page reviews under the shared eight-call limit. Source-bound
qualitative context retains its original page and verbatim proof. Complete
supplementary source requests have an explicit 36,000-character capacity; oversized
requests still fail without truncation. Calculated amounts and count changes
must bind to exact Python results, units and period pairs. Explicit magnitude
comparisons preserve the signed raw observations.

The final identifier, count-change and magnitude repairs have not yet been
verified in another fresh real-model run. Work is paused at the user's request
after committing and pushing this checkpoint. The earlier 17-minute success
remains the only completed original-PDF baseline documented here.

Pre-commit regression checks ran 1,077 cases: 1,063 passed, 13 were optional
skips, and one fiscal-label/identifier regression failed. After excluding fiscal
and quarter/half-year period identifiers from the qualitative identifier rule,
all 64 source-context, publication-copy and declared-amount checks passed.
The full regression suite was not rerun for this paused checkpoint.


## 2026-11-13 second paused development checkpoint

Further repairs preserve signed count changes and explicit magnitude semantics,
source-owned discussion years, complete months-ended dates, month/year labels
and exact future-duration conditions. Unchanged adjacent qualitative statements
are grouped into at most four paragraphs so they fit the existing bullet limit
without dropping source qualifications. Complete calendar dates now bind
calculated percentage changes to their exact Python intervals.

Owned page writers retain a misplaced typed root quotation by moving it unchanged
into context_evidence. Reading fact locator keys with a duplicated line suffix
retain their supplied coordinate; conflicting or missing coordinates still fail.
Initial copy repairs must return an explicit complete evidence list rather than
silently retaining rejected draft citations through null. A similar original
paragraph may be shown as correction feedback, but never gains evidence approval
from similarity. Independent reviewers now receive the applicable exact Python
calculation catalog and input IDs. Transport recovery allows one same-provider
retry for an unclassified APIError, records real HTTP status codes when available,
and preserves the existing authentication, bad-input and unsupported-operation
failure paths.

Targeted phase checks passed, including 1,086 affected regressions (13 optional
skips) before the subsequent repairs, and later focused groups covering source
notation, provider transport, quotation handling, source-line ownership and
review calculation scope. The last two focused groups passed 97 checks (3 skips)
and 58 checks (8 skips). The complete suite was not rerun on this checkpoint.

Fresh attempts 19 through 26 stopped before PPT export at validation or provider
errors. Attempt 27 was stopped at the user's explicit request before completion.
The final reviewer-input and initial evidence-list changes have not completed a
fresh real-model run. No new qualifying PPTX exists, and original-PDF completion
within 15 minutes remains unverified. Source PDFs, model outputs and private run
diagnostics are excluded from this commit. Work stops after commit and push.


## 2026-11-16 user-requested development checkpoint

Simulation work stops at the user's explicit request. The latest fresh attempt
ended before briefing and export after 536.259 seconds and 90 GPT-6 Luna calls.
No new qualifying PPTX was produced. The final changes below have not been
verified in another fresh real-model run; this checkpoint does not establish
completion within 15 minutes.

The repairs operate on source-bound types and evidence, without company names,
document-type workflows, fixed source pages or document-specific decision paths.
Exact calendar spellings and reporting-period references retain their source
ownership. Signed monetary, count and day changes bind to deterministic Python
results, explicit metrics and comparison periods. The compiler, reviewers and
final validators share calculation catalogs rebuilt from each page's explicit
input IDs, while other tables' conflicting records remain available. Reported
currency rates preserve their numerator scale and exact source denominator;
ordinary totals cannot supply price evidence.

Long or cross-page qualitative proof can retain bounded continuation quotations.
Each passage keeps its physical page and must bind literally; splitting does not
delete words, merge missing text, approve meaning or enlarge the existing total
page evidence capacity. Known misplaced continuation fields can be relocated
losslessly, while conflicting and unknown fields still fail. Scope feedback
identifies unsupported fiscal/interim labels rather than converting dated
balances. Shared qualifier ambiguity remains disclosed and independently
reviewed. Short finding references reduce identifier transcription errors and
map back to the original IDs before retention.

Visible-copy feedback measures the combined paragraph and source-context budget.
The existing copy limits, bounded corrections, independent source review and
export gates remain mandatory. An omitted overall reviewer rationale receives
one format correction only when all substantive verdict fields stay identical.
No model/provider fallback or Local Only policy was changed.

Phase regressions cover multiple currencies, scales, native units, source-date
notations, wrong signs/periods/metrics, duration conditions, ambiguous qualifiers,
multi-page proof and malformed evidence transport. Private PDFs, model outputs,
run diagnostics and credentials remain excluded from the committed tree. No
further simulation is started before this checkpoint is committed and pushed.

The final local checkpoint regression group passed 447 tests in 115.30 seconds,
including typed prices, calculation provenance, source-proof transport, semantic
scope, gateway policy and provider credential isolation. Streamlit's local UI
checks required running outside the sandbox's loopback restriction. The complete
suite was not rerun after the final changes.

## 2026-11-23 fresh acceptance checkpoint

The final authorized run used the original 524-page public HKEX prospectus and
OpenAI GPT-6 Luna. It started from PDF ingestion with `checkpoint: null`,
`resume_supplied: false`, and `request_cache_enabled: false`. The 900-second
limit included native PowerPoint export and rendered QA.

The run stopped at presentation selection after 397.051 seconds and 90 recorded
model calls. One final replacement explanation contained 814 characters against
the 700-character field limit. The report did not reach PowerPoint export, so
completion within 15 minutes remains unverified. The two description-only
requests used low reasoning effort and returned complete responses. The field
limit remained enforced.

The pre-run regression group passed 508 tests, with three skips. This checkpoint
records one fresh acceptance attempt. The source PDF, run receipts, and model
responses remain in ignored local output.

## 2026-11-24 fresh acceptance checkpoint

Round 53 ran OpenAI GPT-6 Luna from the original 524-page public HKEX
prospectus with no supplied checkpoint and the application request cache
disabled. The run took 604.882 seconds and recorded 111 model calls and
4,620,762 total tokens. It retained 1,621 observations and 20 deterministic
analysis results, completed the five-page company introduction, and
completed both supplementary source reads.

The independent analytical-page review required two corrections to the
inventory discussion. The page needed to distinguish the increase in the
share of gross inventory aged more than one year from a rise in its absolute
amount, and to disclose qualitatively that a substantial portion of the
June 30 inventory was used or sold by October 31, 2024. The run halted at
presentation selection without a PPTX. The 900-second end-to-end criterion
remains unmet. Local receipts are under the ignored
`output/fresh-luna-20261124-53/` directory.
