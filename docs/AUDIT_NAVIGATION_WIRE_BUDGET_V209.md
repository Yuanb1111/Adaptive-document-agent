# v209: bounded report requests, physical scope and exact source quantities

The `.138` v208 checkpoint stopped before the audit discovery model call. Its
68 targets and complete 524-page navigation occupied 261,982 characters in the
canonical local ledger, just above the 260,000-character navigation cap. The
guard measured this ledger before the existing request-local short-reference
mapping. It also counted JSON separator whitespace that need not be transmitted.

Discovery now uses one shared serializer for admission and the gateway payload.
It first applies the existing reversible reference map, then compact JSON
serialization. All target fields, source text (including whitespace inside
strings), page-index entries, literal navigation hits and source checks remain
intact. On the unchanged `.138` input, that exact payload is 251,080 characters.
The 260,000-character cap is unchanged; an actual oversized payload still fails
before any model call. This does not provide unbounded navigation capacity.

The canonical ledger and its complete-source fingerprint remain unchanged.
Selected pages still require full reading, literal validation and independent
assurance review. No retry, page-selection, audit-context, privacy or export
limit was increased. The application version advances to v209, with extraction
and analysis cache versions unchanged. Discovery diagnostics record the actual
serialized payload length.

The first live continuation completed discovery and all 23 audit batches for
68 targets, then failed the independent physical page-budget gate: the model
retained 14 analysis pages and subsequently removed only a two-page topic while
claiming to fit the 10-page analysis limit. The second proposal still had 12
analysis pages and 21 body pages. This failed run is not counted as success.

Budget feedback now provides Python-calculated whole-topic reference options.
It enumerates subsets only when actual native page mappings prove topics have
disjoint additive costs, with at most eight topics (255 nonempty combinations).
Every offered combination fits the current analysis and report caps under the
measured overhead. Shared, missing or inconsistent page mappings produce no
inferred subset costs. The model still decides importance and omissions from
complete evidence; options carry no semantic approval. Partial-series savings,
new copy and a new briefing still require native measurement. No extra selection
attempts or relaxation of independent review/export gates were added.

The model still repeated an 11-page analysis scope after receiving arithmetic
feedback. Whole-topic choices therefore now use a structured scope operation
inside each existing proposal slot. The model selects an exact feasible option
ID and supplies the full source-aware series decision ledger. Python copies
only those exact original topic objects and validates every include/omit
decision, including shared series. It cannot rewrite or rank source claims.
If source-faithful partial-series editing is needed instead, an explicit
`refine_series` response routes to the existing full proposal operation. Both
routes retain the two-proposal limit, independent semantic/omission review and
actual native page checks; reference costs never certify the final deck.
The partial-series route uses a scope-planning call before the existing author
call; it does not create another proposal slot.

A subsequent replay stopped at topic source semantics: extracted percentage rows
did not carry their table introduction and geographic definition, although the
same original page contained both. Topic review now receives complete pages
cited by its selected rows, with explicit per-topic ownership and missing-page
markers. It cannot borrow another topic's sources or silently select additional
series. Existing capacity partitioning counts the full pages and never truncates
them. New approvals hash both the exact rows/draft and full owned source text.
Prior row-only approvals retain their original scope; once a contextual review
exists for that exact draft, changed pages cannot fall back to an old row-only
approval. Supported siblings are not promoted to full-page approvals without a
corresponding review.

The next live continuation selected a feasible whole-topic scope on its first
proposal and passed independent omission review, with 20 total pages, 19 body
pages and 10 analysis pages. It then failed the briefing's exact quantity gate:
the author and bounded repair rounded source-native thousands into millions.
That run also is not counted as a successful export.

Numeric item repair now offers item-owned references to exact signed amounts
already present in the supplied source options. The model chooses references
and writes connecting prose; Python inserts the chosen amount strings without
rounding, rescaling or choosing analytical meaning. An unambiguous literal
per-unit denominator is retained; ambiguous denominators are not inferred.
Reference arrays reject unknown IDs, inline monetary literals and incompatible
positive-magnitude annotations. Legacy literal replies remain compatible but
receive no rewriting or additional trust. Expanded copy still passes the
existing number, currency, sign, source, length and independent meaning gates.
The one-patch limit and residual-correction progress gate remain unchanged.

## Validation

- 43 focused tests passed, including a synthetic 68-target, 524-page boundary
  case, exact gateway payload comparison, retained source whitespace, unchanged
  raw state, complete-source fingerprint invalidation, exact-limit acceptance
  and rejection one character over the actual wire limit before a model call.
- 531 audit, privacy and Local Only regression tests passed.
- 283 budget regression tests passed; the final ten cost-option tests also
  passed after adding an explicit check of each report-scope cap.
- 28 source-page/review tests passed, followed by 727 topic, budget, privacy and
  Local Only regression tests. These suite counts overlap and are not additive.
- After structured scope binding, 284 budget regression tests and 19 focused
  cost/scope tests passed, including invalid choice IDs, shared series,
  incomplete decision ledgers, unchanged source copy and privacy propagation.
- 748 briefing regression tests and 11 focused quantity-reference tests passed,
  covering exact negative amounts, units, denominators, unknown references,
  split inline monetary literals and unchanged rejection of incorrect legacy
  literal amounts. These suite counts overlap with earlier runs.
- The original `.138` input was measured locally without modifying it. Its
  canonical and wire sizes are recorded above; all 68 targets and 524 navigation
  entries were retained.
- The final diagnostic continuation passed reporting and strict PPTX export in
  556.5 seconds with 26 real gateway calls and gateway caching disabled. It
  replayed the previously accepted exact scope choice, the failing briefing's
  cited-page set and the exact failing briefing draft. Repair, independent
  reviews, supplementary-source integration and translation used the real
  configured model. This is a saved-checkpoint continuation and targeted failure
  replay, not a new PDF extraction or an unmodified one-click end-to-end run.
- The model used exact quantity references for all four numeric repair items.
  Remaining source/meaning errors went through the existing bounded correction
  and salvage gates. The final report passed completion and physical budgets:
  20 total slides, 19 body slides, 10 analysis slides and one data-index slide.
  The exported PPTX was reloaded and independently checked against those gates.
  Original document and observation objects matched the original `.138` file
  exactly. Strict local rendering QA passed on its first attempt with no issues
  or layout repairs. Artifact SHA-256:
  `d1a03199c81f37ebb7f1f2bfdcaede3d2db43f79f910511809d934b4328dd8bd`.
- Private diagnostics and model validation artifacts remain under ignored local
  paths and are excluded from the commit.
