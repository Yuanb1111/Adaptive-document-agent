# v207: literal counterpart correction feedback

## Failure and change

The `.005` v206 checkpoint stopped in `report_audit_scope`. Two different
proposals failed: an amount on a covered statement appeared only in an unlabeled
subtotal, and another proposed summary amount had no literal aggregate row on
the cited statement. The first validation response reported the proposed metric
and amount as expected source text. The writer then copied the labeled summary
from another page into its counterpart quotation, exhausting the existing
binding correction allowance.

The validator still requires literal quotations, exact signed amounts and units,
source scope, and independent semantic approval. Its feedback now distinguishes
editable counterpart proposals from retained facts. The writer and reviewer are
explicitly told that a missing label cannot be borrowed from another page or
neighboring row, and component arithmetic cannot create a literal counterpart.
They must search supplied pages for a complete supported counterpart or justify
an unresolved disposition for independent review.

A focused helper supplies bounded, continuous reading windows around the exact
proposed signed amount on the previously proposed page. It includes original
character offsets and the amount line, reports whether the proposed label occurs
on that page, and marks both semantic correspondence and assurance as
unestablished. It does not infer row identity, select a status, stitch fragments,
or replace full source pages. Missing or overlong windows remain absent with
explicit diagnostics.

No retry budgets, literal evidence predicates, raw observations, calculations, source
pages, provider routing, or Local Only rules were weakened. The extraction and
analysis cache versions remain unchanged; the application version is v207.

## Export scope correction found during continuation

The `.005` reporting continuation then reached strict export, where a legacy
keyword check rejected two turnover-day charts in an independently reviewed
working-capital topic. The hyphenated wording missed the legacy topic alias,
while the question's cash-flow wording triggered a conflicting-topic rule.

For parallel panels only, the scope validator now recognizes an exact existing
semantic topic review before falling back to keyword matching. The observation
must still be valid, selected by that topic, and linked to both the actual slide
and theme. The approval fingerprint is recomputed from current topic copy and
all selected source rows: edited copy, IDs, values or evidence cannot reuse it.
Chart captions, arithmetic, units and source evidence retain their separate
validators. This does not add a document-specific topic synonym or approve a
new semantic relationship in Python.

A subsequent export in a new process also exposed nondeterministic assurance
copy. `slide_context_notes` collected displayed observation IDs in a set, so
metric-name order varied with Python's hash seed. The localization inventory
and a later export could therefore disagree on otherwise identical text.
Observation IDs now retain the authored chart/slide/block order with stable
deduplication. Changed display strings still undergo model translation and
independent review; language coverage checks are unchanged.

## Validation

- 38 focused tests passed, including unlabeled subtotals, missing aggregates,
  independent rejection of unknown dispositions, fabricated cross-page labels,
  signed amount boundaries, bounded windows and unchanged source data.
- 543 selected audit, privacy, Local Only and source integration regression
  tests passed.
- Both exact first failed `.005` proposals were replayed unchanged locally.
  Their corrections and independent reviews used the configured model through
  `LLMGateway`, with response caching disabled: four real calls, one existing
  binding correction per batch, and no added retry allowance. Both batches
  completed; the two problematic counterparts remained unresolved. This replay
  checks the original failure/correction path, not a fresh PDF analysis.
- 75 focused topic-scope tests passed, including stale source/copy rejection,
  missing review, ownership, comparison mode, and incorrect chart captions.
- 540 broader topic, QA and parallel-panel tests passed; one external-fixture
  test was skipped.
- 16 assurance-copy/scope tests passed, including chart and direct-observation
  notes in separate processes under three different hash seeds.
- 33 context-note and presentation-language regression tests passed.

The `.005` checkpoint was continued from its failed audit stage through the
production reporting gates with response caching disabled. All 17 audit targets
completed, followed by budget, briefing, source integration and display-language
checks. Reporting used 31 real calls; reviewing the changed stable display copy
used two more. The final strict `export_pptx_with_report` call ran in a separate
process, with no force flag or completion-gate bypass. The actual saved PPTX
passed budget validation: 18 slides, 17 body slides and one data index. Local
rendered QA passed on its first attempt with no issues or repairs and preserved
facts. Reloaded observations and all original document pages exactly matched
the original `.005` checkpoint. This is saved-extraction continuation, not a
fresh PDF-to-extraction rerun or a guarantee for every future model response.

Private checkpoints, prompts, model outputs and source documents remain in
ignored local diagnostic files and are excluded from the commit.
