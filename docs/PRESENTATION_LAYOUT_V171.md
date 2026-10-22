# Chart-pair support sidebar v171

Version: `2026-10-22-chart-pair-support-sidebar-v171`

## Change

When two charts with an explicit supporting table exceed their original layout's
capacity, the compositor now tries a side table before splitting the topic.
Chart widths respect the existing per-chart minimums; each chart still passes
the measured title, legend and inner-plot height checks. The complete table and
commentary use the remaining column. Explicit KPI layouts retain their roles.

The candidate is accepted only if all content fits on one page and composed
geometry validates. An overflowing or undersized candidate is removed in full,
then the existing pagination path runs. Invalid evidence is not swallowed as a
layout failure. No labels are shortened and no table rows are removed to fit.

The candidate retains the leading chart's caption from the ordinary split.
Without this, combining the chart set can select a different generated caption
and invalidate the existing display-language review. Geometry must not change
the reviewed analytical display copy. The original plan remains unchanged.

The implementation uses available geometry and selected visual roles, with no
issuer, metric-name or document-type conditions. Extraction and analysis
contracts remain unchanged.

## Actual `.256` validation

The export reuses the completed v170 `.256` analysis and makes no model calls.
Normal preflight and local rendering pass with empty issue lists. All 17 native
charts retain exactly the same names, series names and values; both native
tables retain identical cell text. Protected analysis and presentation-plan
fields compare exactly equal, and existing source-review decisions remain valid
within their original scope.

The R&D charts and complete support table formerly on pages 14–15 now fit on
page 14. Both native chart boxes measure 3.86 by 2.71 inches, exceeding their
minimum readable dimensions. All source context from both old pages remains
visible. The deck has 18 pages instead of 19; Data Index is page 17 and the
official thank-you page is page 18. Current source-trace page numbers were
checked against the physical deck after reordering.

The combined page was visually inspected at full size and the contact sheet
reviewed for deck consistency. The first 13 pages are pixel-identical to v170.
After shifting forward one page, conclusion and index content is pixel-identical
above the page-number band, and the official closing is entirely pixel-identical.
The conclusion, index and closing content follows the combined page. Local
rendering does not certify parity with every PowerPoint or Google Slides version.

Private artifacts under `output/v171-256/` include:

- `analysis_presentation_v171_256.pptx`
- `analysis_data_v171_256.json`
- `export_audit.json` and `layout_comparison.json`
- `render-final/` with all slide renders and a contact sheet

## Tests

The initial capacity/table/layout suite passed 34 tests. The focused final
suite passed 22 tests, including three new cases: measured side geometry with
minimum-width rejection; one-page native charts/table with preserved caption,
values and source notes; and full rollback of a sidebar requiring continuation
pages without duplicate charts or lost rows. Existing single-chart recovery and
invalid-evidence checks remain in the regression suite.

The full run passed 5,209 tests and skipped 14, with one obsolete assertion
requiring two pages for an expense comparison that now fits on one. The assertion
was updated to one page while retaining every chart-height, complete-period,
source-value and sign-convention check. All 39 tests across the affected layout
files then passed (`output/pytest-v171-final-layout.log`). No production code
changed after the full run or actual export. The full-run log records four
existing dependency/Windows event-loop warnings (`output/pytest-v171-full.log`).
