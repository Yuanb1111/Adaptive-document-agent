# Source subtotal export validation (v84)

## Export blocker

A model-selected supporting series could be rejected even when the source table
explicitly reconciled it to the slide's main measure. The previous three-row
subtotal proof only accepted the second addend. It now accepts either preceding
addend, using the source row order and signed deterministic arithmetic.

The supporting observation must still be selected and declared by the model for
that topic. All three rows must retain matching units, currency, scale, period,
entity, category, parent, dimensions and accounting qualifiers. The proof binds
the exact resolved table, page, row label, raw cell and normalized value. Conflicting
copies, ambiguous alignment and failed reconciliation remain blocked. A chart's
own title is checked independently and cannot borrow the slide's supporting role.
No document type, issuer, financial equation or source page is hard-coded.

## Downloadable diagnostics

When PowerPoint export fails, the analysis JSON now includes
`pptx_export_diagnostics` from that exact attempt, including the stage and error
codes. The separate QA download uses the same snapshot. A successful retry does
not retain an earlier failure. The analysis model and build-cache inputs remain
unchanged, and unknown exception messages retain their existing redaction.

## Presentation organization

Short supporting definitions use the same measured text capacity as the inline
commentary renderer, avoiding a separate continuation when the text fits beside
its evidence. Closing findings with the same complete period headers participate
in balanced pagination even when their units differ; each unit retains its own
labelled table. Rejected model wording stays in the audit rather than creating a
generic coverage page. Genuine source conflicts, missing topics and limitations
remain visible.

## Validation

Regression cases cover both signed addends and nonfinancial measures, source
scope, raw cells and scale, selection, conflicting copies, qualified row labels,
and strict chart captions. Download tests cover financial, native preflight,
rendering and generation failures, successful retries and message redaction.

The saved latest analysis was replayed locally against the matching source PDF,
without additional model requests. The original observations and their evidence
remain unchanged. The selected 15 native charts are retained, and financial,
native preflight and rendered export checks pass. The final replay produced
21 slides, including one Contents page, with an export duration of about
18 seconds on the local verification runtime.

Final verification: 2,808 Python tests passed, 8 skipped, with three existing
provider-mock event-loop warnings. The skipped tests require opt-in Linux
rendering/font integration. No paid model requests were made.

The saved model-written executive brief remains unavailable. Its audited
rejection includes missing date-header evidence and sign qualifiers. This
replay retains the existing verified topic-based summary; it does not generate
new model prose or relax the brief's evidence checks.

The pipeline version is v84. Analysis remains v41 and extraction remains v2,
because this patch changes export validation and serialization rather than the
model-analysis or raw-extraction contracts.
