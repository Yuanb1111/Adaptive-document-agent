# V216: reuse validated analysis for reporting

## Problem and reference run

The user's V202 run (`2026-10-26T180602.973`) completed in about 693 seconds.
Its logged tokens cost approximately CNY 2.885 when normalized to the same
peak price band used for comparison. This is a token-ledger estimate, not an
account statement. V202's initial topic pass failed; its successful presentation
reused existing validated model findings. It was not a successful exhaustive
review of all extracted series.

The V214 `.087` run, on the same 524-page PDF and same 1,623 observations,
recorded 88 model requests and approximately CNY 4.597 of known peak-band
token cost. The 900-second deadline stopped it without a complete presentation.
Its repeated topic selection, topic evidence review, coverage review and report
audit-scope reconstruction accounted for approximately CNY 2.26 of those tokens.
These are observed historical operation groups, **not guaranteed savings**:
necessary audit work still depends on actual final claims.

The acceptance target is CNY 2–3 and a complete PPT within 15 minutes. V216
reduces repeated reporting work toward that target; it does not claim a new
live cost or latency measurement. The development environment has no configured
DeepSeek API key, and no paid provider calls were made during this change.

## New default route

`LLM_PRESENTATION_STRATEGY=retained_analysis` is the default. After the usual
model scoring, deterministic calculations and insight validation:

1. Build the report outline once.
2. Make one bounded `RetainedAnalysisSelection` request over the existing
   findings, their exact inputs, calculations and user requirements. The model
   decides inclusion, omission and narrative order. Every eligible finding
   must receive a decision; findings that lack valid input bindings remain
   visible as unavailable rather than silently disappearing.
3. Compile the selected validated wording and exact evidence into analytical
   slides. Python does not rank topics by keywords or create new findings.
   The existing fallback compositor supplies structural cover/intro/summary/
   appendix scaffolding only; its heuristic analytical ranking is discarded.
4. Keep introduction, executive-brief, arithmetic/direction, audit-scope where
   required, supplementary-source, localization and physical-layout checks.
5. Run one independent `RetainedAnalysisReview` on the final analytical pages,
   complete analysis inputs, related period series, source pages and omissions.
   Reject missing source pages, changed selection, rejected/missing/duplicate
   verdicts, material omissions or stale approval. PPT export checks this gate
   before and after native composition.

This route reviews **model-selected analysis**, not every extracted metric.
Full extraction and original source records remain in diagnostics. Existing
failed topic/coverage reviews are not cleared simply by changing routes.
If no reusable valid findings exist, the existing catalogue workflow remains
available. Set `LLM_PRESENTATION_STRATEGY=full_catalog` to explicitly select that
workflow. Historical replay tests now declare that strategy instead of silently
depending on an old default.

The new selector has an 8,000-output-token cap and uses the existing configured
policy for selecting already validated content. The independent source reviewer
retains provider-default reasoning and has a 16,000-output-token cap. Neither
operation uses a second format-repair/full-catalogue fallback request. Rejected
semantic responses are removed from the gateway's request cache. A retry still
requires fresh approval; a failed review never authorizes publication.
If selection itself fails, reporting returns a diagnostic checkpoint and drains
background work before purchasing executive-brief or localization calls.

## Evidence and request size

The review uses the existing audit module's complete-page-text and source-column
position view, including adjacent pages for carry-over headings and footnotes.
It does not clip pages into ranked snippets. Full original source/table/layout
records remain stored; their hash also participates in the approval binding,
including finer coordinate changes than the compact reading view displays.
Only independently validated audit bindings enter the reviewer context; raw
historical audit drafts are retained in diagnostics instead of copied again.

Repeated structured records use a reversible column encoding, preserving raw
values, nulls, row order, nested fields and reserved-key literals. Display
translation caches are excluded from original selection identity because they
have their own independent translation gates. User requirements remain bound.

Private offline projections using five synthetic selected findings produced:

| Saved source | Native body pages | Analysis pages | Introduction pages |
| --- | ---: | ---: | ---: |
| V202 successful reference | 14 | 5 | 4 |
| V214 `.087` failure | 17 | 5 | 5 |

These projections exercise actual native composition and source references;
the five-finding choices are **synthetic**, not new model decisions or evidence
approval. They do not establish live latency, semantic quality or billing.

Before wire encoding, selected-analysis request contexts measured 112,464 and
125,943 characters respectively. The equivalent encoded requests measured
83,572 and 92,504 characters. These are payload characters, not token counts.
The prior V215 `.087` all-series selection request was 234,667 characters.

## Validation and remaining live check

Regression tests cover the real gateway, complete synthetic reporting and PPTX
export, independent rejection, missing source pages, mutated raw values/claims/
calculations/requirements/geometry, omission and verdict completeness, stale
selections, lossless encoding, local-only routing, cache rejection eviction,
reasoning policy and unchanged full-catalogue workflows.

The full offline suite passed 6,293 tests, with 14 skips and five dependency
warnings (569.28 seconds). The final selection-failure checkpoint changes passed
57 targeted tests; the final UI/configuration and new-route export checks passed
45 targeted tests. These focused counts overlap the full suite. Windows skips
the separately opt-in Linux/LibreOffice and private checkpoint integrations.
The test runner blocks external networking. Private PDFs, JSON logs and generated
projections are not committed.

The next live run must show the V216 version and record the two new operations.
Compare complete PPT delivery time and the account debit with the V202 baseline.
Model/provider latency, source complexity and genuine evidence failures can still
prevent the target; the 15-minute deadline and publication gates remain in force.

Extraction-v23 and analysis-v88 stay unchanged; V216 changes the reporting route,
not extracted evidence or the arithmetic engine.
