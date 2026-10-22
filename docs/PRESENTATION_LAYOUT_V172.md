# Standalone-table readability v172

Version: `2026-10-22-standalone-table-readability-v172`

## Change

A standalone full-width exact-data table previously used the same 14 pt type
and compact row heights as a small support table. This left avoidable empty
space on a page containing only a short table.

The compositor now measures complete cell copy at 18, 16 and 14 pt, selecting
the largest size that fits the entire table, including its header. Row heights
follow the selected font and measured wrapping. It never enlarges a subset at
the cost of extra pages. Tables beside charts or commentary retain their compact
type. A table that needs pagination and all its continuations remain at 14 pt,
including the final fragment. Existing group-preserving page breaks still apply.

The new measurement helper is independent of metric, issuer and document type.
No labels, periods, values, signs, units or evidence are shortened or inferred.
Extraction and analysis version contracts remain unchanged.

## Actual `.256` verification

The completed, source-reviewed v171 checkpoint was re-exported with no model
calls. Normal export, preflight and local rendering passed with empty issue
lists. The deck remains 18 pages with 17 native charts and two native tables.
Data Index remains page 17 immediately before the official closing on page 18.

Page 12's six-row table now uses 18 pt instead of 14 pt; its height increases
from 2.80 to 3.60 inches. Its full cell text is unchanged, and the table fits
above the original source footer without a new continuation. The full page was
visually inspected and the contact sheet reviewed. Pixel comparison confirms
the other 17 pages are identical to v171, including all chart layouts and the
combined chart/table page introduced in v171.

All chart names, series names and values remain exactly equal. Both tables have
identical cell text. Document, observations, analysis plan/results, insights,
charts, executive brief, presentation plan and topics also compare exactly
equal. Source-review decisions remain resolved within their existing scope.
Local rendering does not certify parity with every PowerPoint version.

Private artifacts under `output/v172-256/` include:

- `analysis_presentation_v172_256.pptx`
- `analysis_data_v172_256.json`
- `export_audit.json` and `layout_comparison.json`
- `render-final/` with all 18 slides and a contact sheet

## Tests

The focused suite passed 35 tests. Seven new cases cover complete-table font
selection at each supported size, fallback for insufficient height, full
multiline text preservation, a short native table enlarged without pagination,
and a 13-row native table retaining 14 pt across both pages with every fact
preserved in order and no geometry overlap.

The complete suite passed 5,217 tests with 14 skipped and four existing
dependency/Windows event-loop warnings (`output/pytest-v172-full.log`).
