# Fallback source-review measurement and diagnostics v202

## Failure reproduced from the screenshot

The screenshot stops at 85%, after supplementary source review, with
`'NoneType' object has no attribute 'topics'`. No analysis JSON is available.
No original run data or server traceback was supplied, so the upstream reason
why topic selection was unavailable cannot be established from this screenshot.

A synthetic full reporting run reproduces the exact error and call path:

1. Topic selection fails; the original failure is recorded, and the existing
   evidence-only fallback has `presentation_topics=None`.
2. Introduction and conclusions complete. Supplementary source review changes
   the conclusion copy.
3. The orchestrator correctly remeasures the final deck and enforces the actual
   physical slide budget.
4. `presentation_budget_refinement.measure` measures the native deck, then reads
   `result.presentation_topics.topics` while constructing optional topic counts.
   It raises `AttributeError` because the fallback has no selected-topic object.
5. The late reporting handler catches expected validation/model failures only.
   The unexpected exception escapes instead of returning `final_result`, so the
   UI receives a failure with no partial result to download.

This is an application state-handling bug, not evidence that the input PDF is
invalid. It is not resolved by relaxing source review, skipping the final budget
check or generating an empty topic selection that falsely implies acceptance.

## Changes

- Measurement handles both absent and empty selections. Native slide rendering,
  body/section counts, export trace and physical budget enforcement still run.
  Only the optional `topic_pages` metadata is empty for a fallback.
- After supplementary copy changes, progress explicitly switches back to the
  existing final PowerPoint budget-measurement stage.
- At the final reporting boundary, unexpected programming exceptions are logged
  with their traceback and converted to an explicitly failed partial result.
  The existing failure fields retain the exact stage, exception type and message.
  Source data, prior audits, original topic-selection failure, conclusions,
  usage and retry checkpoint survive. Completion is not granted.
- The existing incomplete-result UI exposes that result as `analysis_data.json`
  without invoking PowerPoint finalization or another model request.
- Completion detection returns false immediately for an already partial result.
  It does not re-enter a defective final review gate while publishing diagnostics.
- Privacy violations, cancellation and process interruption still propagate;
  they cannot turn into reporting fallback or cloud fallback.

The catch boundary is intentionally late, where a complete retained analysis
object already exists. It does not claim to recover arbitrary earlier failures
or restore a previously discarded server-side result from a screenshot.

## Validation

Before the fix, the new suite reproduced five failures, including the exact
`measure` traceback and loss of the partial checkpoint. After the fix, focused
tests cover:

- Real two-pass supplementary source review followed by native PPT measurement,
  with absent and empty topic selections.
- The full reporting fallback path after conclusion copy changes.
- Budget rejection after actual measurement, without marking the run complete.
- Unexpected source-review and measurement errors returning serializable partial
  results; the real incomplete-result download renderer emits the retained JSON.
- Original source observations and failure diagnostics retained.
- Privacy rejection, cancellation and process interruption not swallowed.

Focused regression: **58 passed**, including the final failure-publication check.
Completion/checkpoint regressions: **77 passed, 5 skipped** after the final
completion short-circuit was added.
Full local regression: **5,887 passed, 14 skipped, 4 existing Windows dependency
warnings** in 455.82 seconds. The completion/checkpoint run above separately
validates the final completion short-circuit and its added regression.
`git diff --check` is clean.
No real provider request or replay of the unavailable private run was performed.

Pipeline version: `2026-10-26-fallback-source-budget-checkpoint-v202`.
Extraction and analysis cache contracts remain unchanged. There are no
document-specific metrics, page numbers, workflows or synthetic acceptance
decisions in the production fix.
