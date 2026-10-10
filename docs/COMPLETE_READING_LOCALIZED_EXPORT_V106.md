# Complete reading and localized export (v106)

The default v105 output lacked introductory slides. The customized output had
analysis JSON but no PPT: translation checks rejected equivalent Chinese
dates/units, and the translated closing title was incorrectly treated as an
empty content slide. This release fixes those code paths without waiving source
evidence or calling partial customization complete.

## Changes

- Summary reading facts allow 600 characters, matching their reader schema.
  They no longer enter a 550-character display schema during evidence checks.
  Executive briefing and final slide limits stay unchanged. Introduction
  coverage still requires an editorial decision and a source-bound item for
  every substantive reading part; related parts may share a slide.
- Audience-copy validation accepts equivalent Chinese calendar dates,
  fiscal/half-year labels, and literal currency/scale names. Coefficients,
  repetition, signs, percentages, periods, footnote markers and explicit
  currency/value/scale bindings remain guarded. No rescaling or calculation
  occurs. Narrow text boxes may use equivalent compact period/quantity labels;
  prose, qualifications and facts cannot be dropped to fit. Prepared wording
  receives independent model review. Original source grids remain literal.
- Translation audits store each original copy ID, source text and text budget,
  plus the prepared response. Failed-item retries retain accepted copy.
  Missing bindings in old audits cannot be reconstructed from changed IDs.
- The closing title has a native shape role that survives translation and
  save/reload. Other short, empty slides still fail preflight. Native paragraphs
  replace escaped soft-break strings, retaining font and paragraph properties.
- Borderless extraction uses independent positioned year headers to establish
  columns when only one full numeric row exists. Unlabelled subtotals survive
  in raw cells only, without an invented analytical metric. Short dot-leader
  section headings no longer split a continuous table. Text-only or mismatched
  geometry cannot supply missing column positions.
- Flow date evidence binds annual/interim periods to literal duration headers
  and source years. It does not construct an unrelated year-end/interim Cartesian
  product. Unsupported briefing copy still fails evidence validation.
- Requirements recognize the exporter's native editable source tables and page
  footers. Source tables use purple headers, bold white text, explicit grid
  borders, readable text and repeated headers on continuations. Completion is
  checked against actual exported shapes and exact retained cells, not a model
  promise. Arbitrary themes remain unsupported.

## Verification

Focused regressions cover the reader/display schema boundary, faithful Chinese
equivalents and rejected quantity changes, localized closing roles, multiline
OOXML properties, sparse-column geometry, raw subtotal retention, bound flow
dates, and native formatting/citation verification.

Final full offline regression: **3,260 passed, 8 skipped, zero failures/errors**.
Provider transport tests use mocks; Streamlit tests connect only to localhost.
Optional external-renderer cases remain skipped. The private Artifact replay
below was executed separately.

Local replay of stored responses and the private source PDF validated all 142
reading parts (57 substantive, 22 headings, 63 layout parts). Re-extraction of
the requested 53-page chapter retained 36 physical table fragments. The two
pieces of one continuous table were joined; a sparse percentage used its
positioned source column. Every retained cell verified in a 63-slide diagnostic
export, which passed all-page local Artifact rendering/visual QA without
critical issues or escaped soft-break text. The 76 exactly bound recovered
translations passed coefficient/date/unit and text-capacity checks.

This replay does **not** establish successful new model-generated introductory
slides or complete Chinese customization: the cached result lacks those slides
and some old translation bindings. Their requirements remain not met/partial.
It also does not prove extraction finds every table in an arbitrary PDF, live
model quality/latency, or PowerPoint rendering parity. Private PDFs, JSON,
diagnostic decks and rendered pages remain outside Git. No live document/model
request was made during these checks.

`PIPELINE_VERSION` is `2026-10-10-complete-reading-localized-export-v106`, with
`extraction-v9` and `analysis-v58`. Restart/deploy this version and run a fresh
customized analysis to accept complete introduction coverage and Chinese prose.
