# v166: substantive source coverage completion

## Problem and changes

The `.848` checkpoint had reviewed all 525 candidate series in nine batches,
but its final synthesis failed. Capacity reduction required every local batch
to shrink by a fixed percentage, even when earlier reductions already made
the complete merge fit. Final correction feedback also exposed independent
decision-ID and source-scope errors serially, exhausting the bounded repair.

Reduction now checks the actual complete merge size and preserves the remaining
first-pass proposals once it fits. Every omission still needs a model-authored
reason. Final merge instructions distinguish selectable prior evidence from
the requested delta decision list; one correction receives both source and
decision-ID errors. Limits on calls, complete source context and immutable
accepted observations remain enforced. `complete_topic_coverage` supports
recovery from a retained analysis without repeating extraction.

Successful reviews now retain a source fingerprint. Changed source facts or
unreviewed selection changes cannot inherit success. A subsequent physical
budget change needs its complete, independently accepted omission ledger.
Legacy checkpoints retain their previous behavior until explicitly reviewed.

Supplementary-source integration is a separate semantic stage after the final
brief and budget selection. The writer reads the complete bounded source pages
and decides covered, include or omit for every source check. Inclusions add
actual source-bound conclusions; covered findings bind existing conclusions;
omissions require a source-specific materiality reason. A separate model call
reviews every decision against the same source pages. Literal quotes, numerical
claims and bindings pass the ordinary validators. One correction is permitted.

The accepted audit binds the exact source checks, source pages, topics and final
brief. Failed or stale semantic review remains pending even if a literal quote
is present. Original conclusions, raw values and extraction are preserved.
Added conclusions are measured against the physical page budget before the
pipeline can finish. No result upgrades bounded reading to a whole-document
review. All model requests use LLMGateway and retain its Local Only protections.

## Actual `.848` replay

The user expressly authorized the configured DeepSeek model to review candidate
series and the required supplementary page text. The replay completed all
525 candidate decisions: one additional series included, 524 omitted with
individual reasons, in addition to the previously accepted evidence. The new
series is Asia-Pacific gross profit margin, shown as editable source tables.

Both supplementary checks passed independent review:

- Risk Factors, pages 37–39: a new conclusion includes early commercialization,
  expected continued losses, demand uncertainty, competitive pressure and
  distributor dependence, with the reported distributor counts.
- Accountants' Report, pages 399–401: an explicit, independently accepted
  omission from the operating conclusions; the supplied opinion supports the
  reported financial figures but does not add a distinct operating finding.
  The audit does not infer contents of accounting-policy notes not supplied.

The replay uses normal export gates, without force export. It produces 22 pages:
20 body pages including five introduction pages and nine analysis pages, plus
two Data Index pages. There are 16 native charts, with series/category/value
caches identical to v165. All display text is English;
the original document, observations, analysis results and insights equal the
original `.848` input. Full-document-review completion remains false.

Every rendered page was visually inspected. This caught a narrow support-table
column splitting a period token; period columns now expand from actual labels
before text wrapping. The corrected deck passed a second actual rendering.
The only preflight warning concerns the existing Data Index after Thank You;
the renderer reports no issues. PowerPoint renderer parity is not certified.

Artifacts and private model audits remain in ignored `output/v166-848`:
`analysis_presentation_v166_848.pptx`, `audit.json`, `content_validation.json`,
source-review checkpoints and rendered pages. Historical failed reviews remain
in the audit; no warning was deleted to manufacture completion.

## Regression validation

Tests cover complete merge capacity, aggregate correction feedback, changed
source facts, unreviewed and independently reviewed budget omissions, actual
source additions, rejected independent reviews, forged quotations, stale
review fingerprints and period-token readability. The final complete run passed
5,158 tests, with 14 skipped and four existing dependency/runtime warnings
(`output/pytest-v166-final.log`). The prior full run found only an obsolete
capacity-error message assertion; its expected failure boundary was updated
and the entire suite rerun. Actual export/source checks are recorded separately
in `output/v166-848/audit.json` and `content_validation.json`.
