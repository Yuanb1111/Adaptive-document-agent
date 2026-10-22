# Chart space and table pagination v170

Version: `2026-10-22-chart-space-table-pagination-v170`

## Layout changes

Previously, a single chart with any commentary reserved a side column regardless
of the amount of copy. A caption of at most two measured full-width lines now
uses a bottom band. The chart receives the full content width. Longer commentary
and explicit support tables retain their side column. Plot-height and evidence
checks still run, and complete captions and source qualifications remain visible.
If a single chart fails its measured capacity check, the existing header-reflow
retry explicitly restores side commentary to recover vertical plot space. Short
captions must not defeat that recovery for charts with tall legends or notes.

Exact-data row pagination now measures all rows before choosing a boundary.
Small evidence groups of up to six rows remain together when they fit on a full
page; a narrow support slot can defer the whole group to a wider continuation.
Oversized groups can still split. When all remaining rows fit on one additional
page, the boundary balances occupied height while preferring complete groups.
Balancing does not add pages or reorder rows. Each continuation repeats headers.

These changes use geometry and existing evidence groups, with no issuer or
document-type conditions. They do not alter semantic selections, calculations,
units, source evidence or extraction/analysis version contracts.

## Actual `.256` export

The export reuses the completed, source-reviewed `.256` checkpoint from v169.
It makes no model requests. Normal export, preflight and local rendering pass
with empty issue lists. All 19 slides are rendered; Data Index remains page 18
and the official thank-you artwork remains page 19.

The native chart on page 15 grows from 7.18 to 11.50 inches wide. Its height
changes from 3.11 to 2.32 inches to accommodate the bottom caption, increasing
its chart-box area by 19.6%. The formerly empty side column is removed. The full
changed page was visually inspected, and the contact sheet was reviewed for
whole-deck consistency. Pixel comparison confirms the other 18 pages are
identical to v169, including both native tables. This sample does not require
additional table pagination; synthetic native-table tests exercise that path.

The series names and values of all 17 native charts are identical to v169.
Document, observations, analysis plan/results, insights, charts, executive brief,
presentation plan and topics compare exactly equal. Existing source-review
decisions remain resolved with their original scope; no new source review is
claimed. Local rendering does not certify parity with all PowerPoint versions.

Private artifacts are under `output/v170-256/`:

- `analysis_presentation_v170_256.pptx`
- `analysis_data_v170_256.json`
- `export_audit.json` and `layout_comparison.json`
- `render-final/` with every final slide and a contact sheet

## Tests

The focused suite passed 74 tests. Ten v170 regression cases also pass, including
an actual native table split into seven and six rows with repeated headers,
all 13 original facts retained in order, unchanged analysis objects, and valid
geometry. Other cases cover caption placement, side support, small-group
preservation, oversized-group progress and variable-height pagination.

The first full run exposed two long-header recovery regressions: the new caption
band also consumed height during the capacity-recovery attempt. The recovery now
uses side commentary explicitly; no source notes or authored copy are removed.
The subsequent capacity/layout run passed all 86 tests. The final full suite
passed 5,207 tests with 14 skipped and four existing dependency/Windows event-loop
warnings (`output/pytest-v170-final.log`). The final normal export was rendered
in a fresh directory; all 19 images match the inspected v170 draft exactly.
