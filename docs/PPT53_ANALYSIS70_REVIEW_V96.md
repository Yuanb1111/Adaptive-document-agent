# PPT53 / analysis70: editorial latency and coverage corrections (v96)

## Evidence from the uploaded run

The user's saved `analysis_data (70).json` identifies v95. Pipeline wall time was
563,244 ms and PPT finalization/export was 33,476 ms: 596,720 ms, or 9m 56.7s.
These are observed timings from that run, not an estimate of v96.

| Stage | Observed time |
| --- | ---: |
| Candidate generation/scoring | 108.0 s |
| Insight generation | 88.7 s |
| Presentation topic selection, including coverage review | 132.7 s |
| Slide planning | 40.1 s |
| Executive brief generation and validation | 80.3 s |
| PPT finalization/export | 33.5 s |

The report outline already overlapped topic selection. Its 22.3 seconds therefore
cannot be subtracted again from total latency. The brief and slide planning were
serial. Original model requests for `ExecutiveBrief`, `ReportPlan` and
`VisualSelection` consumed approximately 114 seconds combined, but that is not
the amount of wall time v96 will save.

The brief retained six source-validated findings after its single targeted patch.
PPT53 has 23 slides. All pages were rendered using the configured local Artifact
renderer and visually inspected. Automatic rendered-page QA returned no issues.
No standalone sparse Review status slide remains; the unresolved coverage notice
is attached to a populated Data Index page. The summary includes recent interim
outcomes, product/geographic changes and a source-bound runway scenario table.

## Changes

- The user explicitly selected lighter writing/layout and preserved deep analysis
  on 2026-10-09. Only `ExecutiveBrief`, `ReportPlan` and `VisualSelection` join the
  existing bounded reasoning reduction policy. Semantic resolution, candidate
  scoring, insights, analytical topic selection and introductory synthesis retain
  provider defaults. Model routing is unchanged. Exact capability/endpoint checks,
  `provider_default` opt-out and all existing source validators remain required.
- Executive briefing can now run concurrently with slide layout after analysis,
  recovery and semantic topic/coverage selection finish. The early introduction
  is attached on the caller thread to supply verified identity. Brief retrieval
  anchors come directly from selected topic evidence, preserving title/order and
  source pages independently of slide pagination.
- Each concurrent brief owns a deep source snapshot and cancellation event.
  The invocation's ExitStack drains it on completion or failure; gateway request
  admission retains the configured global capacity. Worker audits are attached
  on the caller thread even after an error. Changed source/analysis/topic inputs
  or failed final source checks reject attachment. Local and stateful Mock
  clients retain serial request order; workers never call Streamlit UI callbacks.
- The actual coverage failure labelled cash generated from operations as included
  while selecting net operating cash flow. Different FY2022/FY2023 values were
  absent; matching one period did not establish equivalence. The targeted repair
  now identifies every missing included fact with its exact raw/normalized value,
  period, unit, definition and source-row/page binding. The strict representation
  gate remains unchanged; Python does not decide semantic importance.
- Coverage contexts encode repeated catalog cells using explicit per-column
  dictionaries and repeated source-period views using named column arrays. All
  source labels, IDs, pages, periods, definitions and values remain recoverable.
  IDs remain literal. Unknown future period-view fields remain literal rather
  than being lost. Failed or incomplete coverage still rolls back atomically.

## Measured offline context savings

Using analysis70's saved topic input and original selection, the initial complete
topic context decreases from 276,387 to 243,184 characters (about 12%). The same
first 29-series review batch decreases from 105,066 to 88,798 characters (15.5%).
At the unchanged 105,600-character target, the first batch can hold 61 complete
series. A fixed-original-selection packing replay fits all 405 candidates in
eight batches with sizes 61, 56, 63, 62, 62, 61, 26 and 14. This is a context-size
check, not model review or a completeness certificate. New selected evidence can
increase later contexts; the eight-batch plus two-repair budget remains bounded.

Regression tests cover actual request payloads/audits and opt-outs for the three
editorial schemas; complete reversible catalog/period encoding; precise repair
feedback; isolated worker state, cancellation/error audits and final input
revalidation; and real-orchestrator cloud overlap versus serial local/Mock order.
Pipeline/analysis caches advance to v96 / analysis-v50; extraction stays v4.

Local verification completed with 3,062 tests passing and eight opt-in Linux/local
rendering tests skipped. The final affected-test rerun passed 175 tests, including
the subsequently added unknown-period-field preservation regression. The offline
generation benchmark also passed (three selector/analysis calls, two briefing
generation/repair calls and one scoring call); its fixed stub timings are not
provider performance measurements. Replaying the actual rejected review confirms
the feedback retains all three original cash-generated rows from page 339,
including raw `(115,664)` and `(119,245)` for FY2022/FY2023.

No live provider upload was rerun for these offline checks. A fresh deployment
and upload must measure the resulting end-to-end time and semantic review quality.
