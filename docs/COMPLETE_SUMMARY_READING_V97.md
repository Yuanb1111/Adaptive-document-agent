# Complete introductory Summary reading (v97)

The previous introduction selected at most eight excerpts and generated fixed
overview/business pages. This could miss Summary subsections beyond those topics,
and selecting a page did not prove its full text was supplied.

## Source and editorial contract

- The gateway selector identifies full introductory Summary/overview ranges from
  page previews and outline metadata. Explicit Summary running headers and outline
  ranges are additional retrieval anchors. This does not impose an industry or
  document-type analytical checklist. Generic documents without a Summary range
  retain the compatible excerpt-based introduction.
- Every selected page's complete original text becomes literal source blocks with
  page and character offsets. Blocks target 6,500 characters, reading batches
  24,000 characters, and total scope 300,000 characters. All batches are processed;
  there is no eight-page or twenty-page reading cut-off. Missing/unreadable pages
  and budget overflow are explicit failures, never a completeness certificate.
- `SummaryReadBatch` identifies semantic parts/continuations and assigns every
  source line exactly once. Each part retains its literal text, page, line range,
  reading note, and up to three source-quoted facts. Layout-only spans are also
  accounted for. Validation checks full page/line coverage and source identity;
  it does not decide section meaning or business importance.
- Reading batches use the configured `LLMGateway`, with bounded cloud concurrency
  and one admission slot left for the main pipeline. Loopback/local and stateful
  clients stay serial. Cancellation drains in-flight work; owners attach the
  isolated result and recheck against the latest source before use. Failed
  reading responses remain in the audit; no alternate provider is invoked.
- `IntroductionDraft` receives all verified parts/notes/facts and chooses which
  to merge, include or omit. Every exact part ID needs a decision and specific
  reason. Included parts must contribute retained evidence to an actual slide.
  There is no fixed overview/products outline or one-slide-per-part rule.
- Dynamic introduction pages allow two to four concise items and at most eight
  pages. Each needs substantive copy (minimum 180 body characters), bound quotes
  and source pages. Unsupported currencies, scales, periods, values, duplicated
  findings, unknown part references and inconsistent decisions are rejected.
  One bounded correction is available per reading batch and final editorial
  response. Failed drafts are audited; there is no invented filler or partial
  reading presented as complete.
- PPT contents use actual introductory titles. Existing branded layouts and
  citations are reused; selected copy must fit a complete page. The first page's
  speaker notes retain the complete reading/decision audit. If all parts are
  omitted, no placeholder is rendered and omission decisions stay in contents
  notes and JSON. Technical Details exposes per-part notes and decisions.

`SummaryReadBatch` and `IntroductionDraft` retain configured reasoning defaults.
The user's earlier lighter writing/layout policy still applies to ExecutiveBrief,
ReportPlan and VisualSelection, not this source reading or editorial selection.
Pipeline/analysis cache contracts advance to v97 / analysis-v51; extraction stays v4.

## Validation and performance limits

The actual analysis70 source contains Summary pages 10–21: 61,078 characters,
12 complete source blocks and three reading batches. This source-size check used
the original retained PDF text and made no live provider request. With the default
four-slot cloud gateway, the three reading batches can overlap during the existing
early-introduction lifecycle; their durations must not be added to pipeline wall time.

Tests cover complete long-page tails and more than twenty source pages; line gaps,
overlaps and missing whole pages; quote/page/currency/scale/period errors; dynamic
merging and exhaustive omission decisions; sparse-page correction/omission;
serial Local Only behavior, overlapping cloud batches, cancellation, changed source,
bounded budget failures, failed audits, full PPT agenda/citation consistency, and
prevention of heuristic profile repair overwriting a completed agent introduction.

A synthetic source-bound deck was generated and all eight physical pages rendered
locally. The three dynamic introductory pages were visually inspected with their
contents page; automated layout inspection found no issues. Its offline 0.765 s
generation time excludes model/network work and is **not** an end-to-end speed claim.
No live upload has yet measured v97 latency or certified its semantic writing
quality. A fresh deployed upload is needed for those comparisons.

The full Windows regression suite passed 3,093 tests with eight opt-in Linux/local
rendering integrations skipped. The final affected-test rerun passed 235 tests and covers the
subsequent empty-audit guard and all-omission speaker notes. Linux deployment CI
runs real LibreOffice rendering on Python 3.11 and 3.12.
