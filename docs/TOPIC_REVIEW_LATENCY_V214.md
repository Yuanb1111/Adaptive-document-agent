# v214: remove false topic repairs and overlap independent reviews

## Evidence from .492

The October 29 `.492` v213 checkpoint stopped at 901.046 seconds during a
`BriefMeaningReview`, after reaching the existing 900-second analysis deadline.
Reporting consumed 487.101 seconds, including 107.422 seconds for insights and
376.439 seconds for topic selection. Stage details are nested and must not be
summed as independent wall time.

Initial topic selection took 138.839 seconds and reported 24,599 reasoning
tokens. Five subsequent topic corrections were triggered by the numeric gate
misreading source-bound `6M` period shorthand as a standalone amount. These
five calls accumulated 69.897 seconds of provider latency, with overlapping
execution spanning about 28 seconds. The first two independent source-review
batches then ran serially, taking 84.079 and 20.394 seconds respectively.

The reviewer also correctly rejected an unsupported reconciliation caveat.
Its correction cited an owned source page, but the numeric gate incorrectly
treated the page locator as an unsupported amount. Later coverage synthesis
introduced genuine metric-ownership and direction errors, which the final
independent reviewer rejected. No performance change may accept those errors.

## Changes

- Topic numeric checks recognize duration shorthand only when the duration
  exists in selected source periods and appears in temporal syntax. A singular
  share qualifier additionally requires selected percentage evidence. Bare
  magnitudes, signed amounts, monetary expressions and unsupported durations
  remain numeric claims. Original prose and all observations remain unchanged
  for semantic review.
- Explicit singular page locators must name an owned source-evidence page.
  They do not authorize the same number elsewhere as a quantitative claim.
- Independent source-review batches run concurrently within the gateway's
  existing worker limit. Local and stateful clients stay serial. Every batch
  retains complete selected facts and complete owned source pages. Corrections
  still wait for the independent verdicts and receive a fresh review.
- Each worker owns its audit. Records merge in source order; the shared
  24-call reservation budget uses a lock. Cancellation and privacy failures
  propagate, and the gateway's shared deadline and admission limit still apply.
- Six topic-selection substages now record separate timings, including failed
  substages. Analytical reasoning policies, batch sizes and evidence gates are
  unchanged. Extraction and analysis cache contracts are unchanged.

## Offline verification

All five original `.492` rejected topic drafts now pass deterministic numeric
validation without any correction request. The saved page-citation correction
also passes. This is not semantic approval: independent source review remains
mandatory.

Replay saved verdicts with:

```powershell
python -m scripts.replay_topic_review_latency "path/to/analysis_data.json"
```

The script uses only a mock client, retains the saved semantic rejections and
does not load credentials. It compares serial and concurrent scheduling using
the same saved verdicts and provider delays scaled to 2%. Measured wall time
was 2.3032s serial and 1.8041s concurrent, with two requests in each case and
identical selection/audit digest:
`a291a8d2be7214980b6fc6a3fcc7607d75492f1fe4b9b088c375c609c13f8659`.
The saved 104.473s of serial provider waiting can overlap; its longest batch
was 84.079s. These figures are a scheduling replay, not a new live model run,
an end-to-end speed guarantee, or evidence of successful final export.

Focused regression initially passed 126 tests. Added cases cover complete
source retention, context propagation, stable audit order, atomic call limits,
local/stateful serialization, cancellation/privacy propagation and deadline
admission, plus duration/amount and page/value separation.

Final segmented regression covers all 6,246 collected cases: **6,232 passed,
14 expected skips**. The initial run passed 4,454 tests before the newly
installed LiteLLM 1.106.6 hit an existing Gemini transport-mock incompatibility
(its unmocked network attempt was blocked). Using the project's established
local dependency set with LiteLLM 1.106.2, all 138 provider-isolation tests passed;
the remaining file segment passed 1,763 tests with 10 skips. The latest focused
43-test run also includes the two subsequently added spaced-sign cases. The
unique total accounts for repeated provider and focused cases, rather than
adding duplicate executions. No provider implementation or dependency
requirement was changed. The existing four Windows event-loop warnings remain.

The full runner blocked external connections while allowing local test sockets.
Initial sandbox attempts were interrupted by Windows temporary-directory and
local-runtime restrictions; successful segments used workspace-owned temporary
paths. Private checkpoint content is not stored in this repository. No live
model generation, final export, commit or deployment is claimed by this work.
