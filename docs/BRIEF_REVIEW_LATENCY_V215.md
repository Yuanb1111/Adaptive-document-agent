# V215: the .087 deadline failure

## Observed run

The private `2026-10-29T102106.087` diagnostic identifies V214 and a shared
900-second analysis deadline. Recorded pipeline wall time is 924,925 ms; an
in-flight provider request finished after the deadline. The final failure is
`AnalysisTimeLimitExceeded`, before the first briefing meaning verdict.

Selected timings (nested/parallel timings must not be summed):

| Work | Wall time |
| --- | ---: |
| Initial topic selection | 160,213 ms |
| Complete topic selection and its reviews | 294,797 ms |
| Report audit scope | 198,719 ms |
| Final briefing meaning review | 90,606 ms |

The final `BriefMeaningReview` request had 26,522 input tokens. Its entire
16,384-token output allowance was reasoning; it returned zero response
characters with `finish_reason=length`. The deadline then prevented the
larger retry. This is missing review output, not evidence that the claim was
rejected. The original candidate was not saved before that first request.

Initial topic selection also had 118,735 input tokens and 26,897 reasoning
tokens. It succeeded, but consumed a substantial part of the shared budget.

## Changes

For shared briefing contexts of at least 32,000 serialized characters, two
mandatory gates divide the work:

- The claim reviewer receives every assigned literal quotation, its source
  audit bindings and the whole current briefing. All existing source, numeric,
  period, qualification and independent audience-direction checks still run.
- A separate context reviewer receives the complete original shared source
  blocks, scope metadata, candidate quotes, audit bindings and whole briefing.
  It checks material omissions, counterpoints, alternative definitions,
  assumptions and companion findings. Its acceptance cannot authorize a fact
  or calculation. The previous contextual sufficiency instructions are retained.

Both gates must complete and pass for an item to be checkpointed as accepted.
A context rejection enters the existing copy repair path; incomplete output
does not. The context gate retains provider-default reasoning, bounded capacity
recovery and one complete-output format correction. Large context review can
overlap source review through the same gateway admission limit. Local and
stateful clients remain serial. Worker progress is delivered on the caller;
workers drain before records are attached. Small contexts keep the existing
combined review path.

The large-context path adds an independent request. Parallelism and narrower
assignments target wall time; they do not guarantee lower total model cost.

Checkpointing now happens before the first model request. Pending items,
candidate copy and complete source context survive cancellation/timeout without
being marked approved. An explicit reporting retry can resume only with the
same complete environment/candidate fingerprint and passing source/coverage
gates. The checkpoint contract changes to v2; old approvals cannot be silently
inherited. Identical checkpoint states are not appended twice.

Large initial topic catalogs also use reversible short addresses. Only typed
ID fields change; raw values, period grids, labels, source quotations, notes
and relationships remain intact. IDs are restored before any existing
validation, correction or semantic review. Unknown IDs remain invalid. The
mapping is retained in diagnostics, and small catalogs keep literal IDs.

## Evidence and limits

`scripts/inspect_topic_request_size.py` reconstructs the selector input from a
saved diagnostic without calling a model or modifying the file. With .087 it
retains all 648 series and round-trips every source field exactly. Serialized
payload size falls from 273,706 to 234,667 characters (14.26%). This is a
reconstructed payload comparison, not the historical full provider request,
a token-count measurement, or an end-to-end speed benchmark.

Offline tests cover concurrent overlap and caller-owned progress, serial
fallback, complete context retention, rejection by either gate, exact index
coverage, truncated output, source/arithmetic failures despite contextual
acceptance, first-request cancellation and resumption, unchanged reasoning
policy, and reversible reference ownership/collisions.

The complete offline regression finished with **6,262 passed, 14 skipped** in
290.79 seconds. Five dependency/Windows event-loop warnings remain. External
connections were blocked by the test runner; loopback was allowed for local
test servers. The skipped tests require opt-in saved fixtures or real Linux
rendering. The private full log is `tmp/v215-full-tests.log`.

No live model run has validated V215 latency or semantic quality on this PDF.
Audit scope still took about 199 seconds in .087 and has not been weakened or
removed. The 15-minute deadline is unchanged. Real completion within that
deadline remains to be measured with a new run.
