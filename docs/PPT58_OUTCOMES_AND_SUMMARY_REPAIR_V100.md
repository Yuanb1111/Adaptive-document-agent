# PPT 58, analysis 75/76: source repair and terminal notifications

The reviewed inputs are the locally downloaded PPT 58 / analysis 75 (Dobot)
and analysis 76, which had no downloadable PPT. Both report v99. The original
PPT 58's 19 slides were rendered and visually reviewed. Neither run retained a
verified company introduction, despite supplying the complete Summary scope
(PDF pages 10–21 and 10–24 respectively).

## Complete Summary reading

- The structured parser previously tried every nested JSON object after the
  outer response failed schema validation. A long fact or note was consequently
  reported as a missing outer `parts` field in the last nested object. It now
  validates the outer JSON value and preserves its actual schema error. JSON
  fences in quoted source strings cannot replace a valid root response; invalid
  roots cannot expose nested answers. Ordinary fenced/prose-wrapped output is
  still accepted.
- Reading facts use the canonical 280-character limit, preserving qualifications
  that were rejected by the narrower 220-character wire schema. Internal notes
  are bounded at 800 characters with a requested target below 400. Audience
  slide items retain their separate 180-character limit.
- The reader explicitly requests contiguous quotes containing a table's period
  and unit headers, not just its numeric row. It must adjust the partition or
  leave a fact empty when that context is unavailable. It must preserve literal
  period spelling rather than introducing unsupported numeric abbreviations.
- Reading annotations may describe context in their supplied block and exact
  page/line metadata. They cannot become slide evidence. Every factual statement
  still validates against its own literal quote and assigned source part; a
  nearby value, year or currency cannot lend support to a fact.
- Every supplied source line remains assigned and every part still requires a
  model-authored include/omit decision. No fixed company-topic checklist,
  forced slide quota, fabricated facts or silent source sampling is added.

## Presentation recovery and layout

- Narrow continuous-date charts show small numeric point labels instead of a
  full date plus value at every marker. The continuous date axis retains unequal
  calendar spacing; exact dates and values remain in native editable workbooks,
  source notes and data appendices. Both chart and text-run fonts are explicit,
  avoiding large inherited template fonts in PowerPoint. Wide panels retain
  full source-date point labels.
- `growth rate` is treated as a measure name, not an assertion of upward motion.
  Separate predicates such as `rose` or `declined` still require unique metric
  scope and compatible source periods. This resolves analysis 76's rejected
  research question and allows all seven selected themes to compile locally.
- Withdrawing an ambiguously bound takeaway also updates its visible section
  and theme headings. Contents, short-title layout and appendix headers can no
  longer revive the rejected heading. Original model topics and rejection
  reasons remain in the audit.
- The generic recovery summary checks each finding against its own explicit
  analysis inputs and retains independent bullet scopes. Rejected titles remain
  in the candidate plan's editorial audit, without mutating the raw result.
  Financial, native preflight and rendered export gates remain mandatory.

## Notifications

Trusted local messages cover: verified completion; completion requiring review;
export blocked by checks; export exception; analysis failure; analysis
interruption; and export interruption. No intermediate model-call notifications
are emitted. Failure state is saved before interruptible UI updates, and saved
terminal events replay when the page mounts again. Opaque outcome/content IDs
and attempt/export-cycle IDs distinguish genuine retries while browser state
deduplicates refreshes. Messages contain no PDF text, filename, provider error
or credentials. Existing permission/opt-out preferences and silent notices stay
intact. Browser permission and an open application tab remain necessary for
system notifications; interruption replay needs a subsequent page mount.

## Validation and limits

Recorded response replay confirmed that all reviewed Summary batch responses
now parse under the correct schema and that exact page annotations no longer
cause false failures. Some old factual quotes still fail semantic/source checks
because they omit headers or use incorrect source spans. They remain rejected:
the revised prompt and correct repair diagnostics need a fresh provider run to
verify the resulting introductory content. The original downloaded files are
unchanged. No claim is made that cached JSON replay measures upload-to-download
latency or establishes live model prose quality.

Local final regression results: 3,146 passed, eight skipped, and three offline
transport tests deselected; those transport tests run in GitHub CI. All 13
browser notification tests pass. Rendered candidates pass on all 19 / 17 slides.

Private candidate builds from both retained analyses pass financial QA. The
analysis 76 candidate retains all seven model-selected themes. Candidates are
locally rendered and reviewed page by page, including PPT 58's cash chart.
Regression coverage includes nested-response rejection, accurate schema repair
errors, qualified fact capacity, reading metadata versus factual evidence,
native date labels/workbooks, growth-rate nouns versus contradictory predicates,
withdrawn visible headings, raw-result preservation, and terminal notification
privacy, retry identities, consent and replay. No document data was sent to a
provider for these checks.

Deploy the pushed v100 commit and reboot Streamlit if it still shows v99.
Pipeline/analysis cache versions change; extraction remains `extraction-v6`.
Fresh testing should confirm the introduction appears, all seven topics remain
available on the second input, compact dates remain readable in PowerPoint, and
failure notifications appear as well as completion notices.
