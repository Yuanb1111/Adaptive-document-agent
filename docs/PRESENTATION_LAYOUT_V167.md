# v167: content-aware presentation layout

## Problem and changes

The `.848` presentation still had short chart areas, a three-period supporting
series split across pages, repeated chart data in supporting tables, and a Data
Index continuation containing only one entry. Fixed commentary reserves and
fixed index columns wasted space even when the copy needed much less room.

The compositor now requires at least 1.8 inches for ordinary native chart boxes
after headings, units and annotations. Composition charts retain their stricter
category/legend measurements. Short commentary uses its measured line height;
it no longer consumes the same band as a supporting table. The KPI band also
measures short commentary, preserving explicit KPIs above readable charts.
When labels and evidence cannot fit, chart pagination retains all selected
charts, source references and complete claims.

Supporting tables omit only complete evidence groups whose exact observation
IDs already appear in native charts. Partially charted series remain complete;
explicit KPI roles remain visible. This applies across chart continuations as
well as within one page. All selected observations remain in provenance notes.
A short support band cannot peel one period off a small complete series: the
whole comparison moves to a suitable continuation when necessary. Compatible
periods and evidence groups still pass the established source checks.

Continuation headings use the reviewed section or measured chart headings;
they do not repeat a long claim in the body. Original section scope remains
available to change annotations, so a continuation does not silently replace
a three-year comparison with the last two years.

The Data Index searches bounded column allocations at the existing 12-point
font size, using measured wrapping. It then minimizes page count and balances
unavoidable continuation pages without reordering or splitting entries.
An oversized entry still fails rather than losing its source scope.

These are generic geometry rules, with no issuer, document-type or `.848`
special cases. Raw extraction, analytical values, topic selection, source review
decisions and language policy are unchanged. Existing saved analyses can receive
the fixes on re-export; extraction does not need to be repeated.

## Actual `.848` verification

The replay starts from the reviewed v166 checkpoint of the original `.848`
analysis. It uses normal export and render gates without force export. The
output has 21 pages: 20 body pages and one Data Index page, with 16 native charts.
The complete Asia-Pacific margin comparison, FY2021 through FY2023, appears
in one table beside the revenue chart. There are no table-only analysis pages.
All six Data Index entries fit on one page at the original font size.

The smallest native chart box increased from 136.65 to 219.32 rendered pixels
in height. Series, category and value caches of all 16 charts equal v166.
Cover, contents and all five introduction pages render identically to v166.
All display copy remains English. The original document, observations,
calculations and insights equal the original `.848` input.

The 525 explicit candidate decisions and both independently reviewed
supplementary-source decisions remain valid, bound to unchanged evidence and
conclusions. Full-document-review completion remains false. Layout changes
neither bypass nor upgrade the substantive v166 source review.

Private input, replay scripts, rendered pages and audits remain under ignored
`output/v167-848`. `audit.json`, `content_validation.json` and
`layout_validation.json` record export, source/content and geometry checks.
The existing Data Index-after-Thank-You preflight warning remains; PowerPoint
renderer parity is not certified.
Every rendered page was visually inspected. The final replay's 21 rendered
pages are byte-identical to the inspected render after the last regression fixes.

## Regression validation

Coverage includes complete versus partial chart/table overlap, measured
commentary height, whole-period support tables, explicit KPI visibility,
long claims and continuation scope, index wrapping and balanced pagination,
and refusal to truncate oversized index entries. Existing layout expectations
now permit readable chart continuations while requiring complete visible facts.
The final complete run passed 5,164 tests, with 14 skipped and four existing
dependency/runtime warnings (`output/pytest-v167-final.log`). The initial full
run exposed two obsolete same-page/title expectations and a KPI-band capacity
regression; their evidence assertions and the KPI geometry were corrected
before rerunning the complete suite.
