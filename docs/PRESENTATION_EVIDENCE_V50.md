# Presentation evidence corrections (v50)

The presentation preparation path now handles four defects found during an
offline replay of a downloaded result. The rules operate on selected topics,
source rows, explicit definitions and comparable periods; they contain no
issuer names, page numbers or document-type workflows.

- Source-defined ratios: the existing topic request receives compact ratio
  definitions linked to series IDs. A deterministic fallback can bind an
  explicit `Calculated by dividing X by Y` footnote to its same-page row and
  marker. It corrects display copy only when one ratio is unambiguously bound.
  Reused footnote markers, multiple ratios and unsupported formula syntax do
  not authorize a guessed denominator. Original copy and literal source
  evidence remain in the validation audit.
- Summary coverage: every retained model-selected topic keeps its own evidence
  references. A logical summary may paginate instead of dropping topics at four
  bullets or forty observations. Ordinary analysis-slide limits remain intact.
  Appendix deduplication also compares the exact periods of each displayed
  table, retaining all source records when one source has additional periods.
- Share claims: each explicit clause binds its own source row, direction and
  denominator. `% of Revenue` can support a revenue-share assertion; unrelated
  percentages cannot. Ranking still requires a complete compatible population.
  Retained model wording from older narrowly repaired plans is revalidated
  before restoration. Repair history survives subsequent editorial reviews.
- Period scope: broad period wording is narrowed to the comparable periods
  actually displayed when the same source also contains other periods. The
  latter are cited separately without combining annual and interim series or
  inventing a new direction claim. Ambiguous periods remain review findings.
  Later direction checks use displayed series, so supplementary references
  cannot silently expand a claim's comparison window.

No additional model request is introduced. Raw observations, original topic
selection and source chart values remain unchanged. The presentation cache
contract advances to v50; extraction and analysis cache versions stay unchanged.

Regression coverage includes nonfinancial ratio definitions, reused footnote
markers, independent share clauses, wrong denominators, summary pagination and
per-bullet evidence, cached-plan idempotency, and annual/interim scope separation.
The acceptance replay renders every output slide locally and compares native
chart values and periods against the downloaded deck.

Acceptance verification: 1,544 tests passed and three platform/opt-in integration
tests were skipped. The local replay produced 16 rendered pages with zero visual
QA issues, six retained summary findings and 12 unchanged native chart series
sets. All 1,470 extracted observations and original model topics/insights were
preserved. The replay made no model calls.
