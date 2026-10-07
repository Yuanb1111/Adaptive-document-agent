# Local claim repair and complete bounded coverage (v86)

The presentation Agent keeps semantic decisions with the configured LLMGateway.
These changes apply to arbitrary documents, without a prospectus workflow or a
mandatory set of financial metrics. Python checks evidence, signs, periods and
presentation capacity; it does not decide which topics are important.

## Retain selected questions during local repair

Withdrawing an ambiguous takeaway no longer restores unrelated raw summary
takeaways. Already validated summary copy and its item-specific evidence bindings
remain unchanged. The affected question, selected themes and raw observations are
retained; the rejected assertion remains in the audit. The no-new-errors gate,
contradiction checks and number/source validators remain mandatory. Questions with
unsupported numbers or unresolved asserted directions still fail safely.

## Review complete evidence within each model request's budget

Coverage review first factors repeated point metadata and encodes columns once.
It retains every ordered raw and normalized value, explicit period, scale,
definition basis, audit status, validation status and source page. Series IDs
remain the model's selection references; original observation IDs and full source
records remain in the lookup and JSON export.

If the complete compact context still exceeds 120,000 characters, review uses
up to eight sequential batches through the same gateway. Each batch receives the
complete facts of its candidate series and accepted selections, plus a catalog of
all series. Deferred catalog entries cannot be selected without their full facts.
No series is sampled or ranked by Python. Exact views already represented by
accepted model selections need no new semantic choice.

Every requested series receives a final inclusion/exclusion reason. Later accepted
complete views can structurally cover an earlier excluded individual view; both
the original semantic decision and final coverage remain in the audit. Changes
commit only after every batch validates. A failed batch, oversized single series
or exhausted batch budget preserves the original selection and records unresolved
coverage rather than presenting a partial review as complete.

## Explicit signed amounts and readable comparisons

An executive brief may declare `quantity_representations` for prose describing a
negative monetary amount's absolute magnitude. The model owns that semantic
declaration. Python requires one exact, uniquely displayed currency/amount/scale
phrase and verifies its absolute-value relationship to a negative quantity in
that item's own literal evidence. Unit denominators still apply. This permits
ordinary loss/outflow wording without authorizing an unannotated sign reversal,
rounding, rescaling or currency conversion. Raw signs never change.

Briefs may also select a `comparison_table` for dense scenarios or comparisons.
All body cells must be contiguous passages from that item's literal quotations;
numeric headers and text pass the same claim checks. Quoted conditional outcomes
and their units cannot disappear. Web and PowerPoint show the same table content.
PowerPoint tables remain editable, paginate whole rows at readable font sizes,
repeat common qualifications and citations, and preserve full copy in notes.
This is a presentation capability, not a document-specific template.

Key Figures retains the selected measure and uses its latest selected,
internally comparable source-row view when available. Different definitions,
categories, units and source rows cannot replace it; annual and interim values
are never used as one direct comparison. The heading describes selected evidence
instead of implying exhaustive document coverage. Signed series show a reported
range instead of highlighting their least-negative value as a peak.

## Applying the update

The presentation contract advances to pipeline v86; extraction v3 and analysis
v42 are unchanged. Use **Reanalyse PDF (ignore model cache)** for a fresh model
selection, coverage review and executive brief. Previously downloaded decks and
JSON files remain historical results. Offline cached replay can verify repair
and transport behavior, but cannot prove a future live model's editorial choices.

Regression tests cover signed magnitude claims and rejection boundaries, literal
scenario tables, complete/failed batch transactions, same-row recent period views,
and preservation of unrelated repaired summary claims. Existing local privacy,
provider abstraction and native/rendered export gates remain active.

Verification: 2,883 Python tests passed, 8 optional checks skipped, and all 7
silent notification frontend tests passed. The representative editable comparison
table passed real local rendering and visual QA. Offline replay of the reviewed
large result retained all six selected themes and passed the native/data/rendered
export gates; its 410 uncovered series completed six bounded transport-review
batches using mock semantic decisions. No live model regeneration is claimed.
