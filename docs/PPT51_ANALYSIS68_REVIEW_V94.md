# PPT51 / analysis68 review and latency changes (v94)

The downloaded v93 run took 836.7 seconds from analysis to export. Its executive
brief stage took 273.6 seconds, including a 164.2-second item patch with 40,415
reported reasoning tokens. Topic selection consumed another 86.2 seconds.
These are historical measurements from that run, not predicted new timings.

## Changes

- Brief requests provide exact page-bound evidence blocks. Models can return
  short block IDs; Python restores literal text and page numbers before the
  existing numeric, currency, period, denominator and qualification checks.
  Unknown references fail validation. Compatible literal quotes still work.
- A single item patch retains all source context and immutable verified items.
  It uses the existing reduced-reasoning preference only on supported routes,
  with a 12,000-token output bound. Provider-default remains available; initial
  semantic briefing generation keeps its original reasoning policy.
- Initial topic selection now shares the complete-point column encoding used
  by coverage review. On analysis68, its data payload is 274,568 characters,
  down from 414,679 (33.8%). Counts exclude prompt/schema overhead. All 1,470
  observations remain intact. Matrix category/value mappings are preserved.
- Ordinary summary findings are packed together before comparison detail pages,
  avoiding a single trailing paragraph after a table. Comparison cells and
  conditions remain complete; original finding order is recorded in notes.
- Sparse text pages and standalone review-status pages fold into existing pages.
  Complete warnings and provenance remain in notes, and copy is visible when
  an existing page has space. Native tables/charts are never treated as empty.
- Accounting amounts such as RMB(59,883) thousand display as RMB (59.883) million;
  raw values, signs and per-unit rates remain unchanged.

## Verification

The saved analysis68 was replayed without live model calls: 21 editable slides,
all original observations unchanged, and no automatic rendered-page QA issues.
The entire rendered deck was also visually inspected. Regression tests cover
reference expansion/rejection, locked patches, full repair source context,
category mapping, summary packing, sparse-page notes and accounting notation.

No new live end-to-end run was performed. Input reduction and removal of lengthy
patch reasoning target observed bottlenecks but do not establish a wall-time
speedup or a promised completion time. Provider output quality and latency need
measurement on the next fresh analysis; existing saved results only validate
export/layout changes. Completed and analysis caches advance to v94 / v48.
