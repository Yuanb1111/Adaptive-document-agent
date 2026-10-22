# Presentation layout v169

Version: `2026-10-22-index-before-closing-layout-v169`

## Changes

Export now moves Data Index pages after the evidence body before adding the
official thank-you slide. Final numbering runs after this order is established.
The existing index relocation rebases source trace page numbers; the closing
artwork remains the final slide for zero, one or multiple index pages.

A narrow support table containing one fact now uses the same compact layout as
a coherent period series: the complete metric label occupies a full-width
heading above Period and Value columns. This removes unnecessary wrapping in a
three-column row. Existing height checks still control whether this layout fits.
Unknown periods retain an explicit `Unspecified` label and any source-column
qualification. No metric names, values, units or evidence are shortened or inferred.

These are generic export and compositor changes. Extraction and analysis
contracts remain `extraction-v23` and `analysis-v88`.

## Validation

The `.256` export used the completed v168 report recovery result at
`output/v168-256/analysis_data_v168_256.json`. The v169 export made no model calls
and reused the resolved, evidence-bound source review. Document content,
observations, analysis plan/results, insights, charts, executive brief,
presentation plan and presentation topics were compared for exact equality.

Artifacts are in `output/v169-256/`:

- `analysis_presentation_v169_256.pptx`
- `analysis_data_v169_256.json`
- `export_audit.json`
- `visual_comparison.json`
- `render/` with all 19 rendered slides

Normal export passed the render gate and preflight with empty issue lists.
Data Index is page 18 and official closing artwork is page 19. All 17 native
charts retain the same series names and values as the v168 export. The existing
source review remains resolved; this export does not expand its review scope.

Visual inspection covered the revised support table on page 14 and the index
and closing pages. Pixel comparison found only pages 14, 18 and 19 changed;
the other 16 pages are identical to the previously inspected export. The closing
artwork is pixel-identical to its previous rendering. Local rendering does not
certify parity with every PowerPoint or Google Slides version.

Five new regression cases cover zero/one/multiple index pages, saved-deck order,
rebased trace metadata, a single support fact with a known or unknown period,
full label/value preservation and composed geometry. The focused layout suite
passed all 31 tests.

The full suite ran 5,211 cases: 5,196 passed, 14 skipped, and one failed because
the existing standard-deck test still required indexes to follow the thank-you
slide. That expectation was updated to require a contiguous index block before
the final closing slide. The complete affected layout and standard-deck test
files were rerun: 38 passed (`output/pytest-v169-final-layout.log`). No production
code changed after the full run or artifact validation. Four existing dependency
and Windows event-loop warnings were recorded in `output/pytest-v169-full.log`.
