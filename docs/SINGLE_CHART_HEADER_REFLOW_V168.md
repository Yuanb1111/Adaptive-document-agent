# v168: recover report sources and readable chart space

## Failure

The v166 `.256` checkpoint stopped at `presentation_budget` with
`_ChartCapacityError`. The same input also failed with v167. A three-panel
composition was correctly split, but its isolated composition chart still had
only 1.589 inches of estimated inner plotting height against a 2-inch minimum.
Its long section heading, question and source qualifications occupied the rest
of the page. The existing recovery could split multiple charts only; a remaining
single chart immediately propagated the failure.

## Change

After an isolated chart fails capacity measurement, the compositor attempts one
header reflow. It uses the existing source-bound chart label as the header and
moves the complete previous heading, subtitle and commentary into the normal
commentary flow. Source context remains visible below the chart. Both attempts
use the normal chart-space and geometry checks; minimum sizes are unchanged.

The retry is bounded and handles capacity errors only. Invalid evidence is not
retried. If the single chart still cannot fit, the error propagates and all pages
created by the failed attempt are removed. Input plans, raw observations,
chart values, periods and source evidence remain immutable.

## Report source recovery

The `.256` checkpoint also contained a rejected conclusion draft and a failed
supplementary risk-source read. A report retry previously reused that failed
read unchanged, so the independent source integration review could not run.
Report retries now reread only saved unfinished targets, using their original
pages, question and decision impact. Completed checks are retained. Invalid
boundaries, missing complete text and repeated invalid quotations remain
unresolved; no absence conclusion is invented. The existing gateway and bounded
source reader are shared with discovery. Earlier responses and failures remain
in the audit, with a new explicit per-retry allowance added to cumulative usage.
Reading these pages does not expand the retained numeric extraction scope.

The failed read exposed a second recovery defect: an otherwise structured
finding exceeded its 1,200-character limit. A format-only repair correctly
preserved its wording and therefore could not shorten it. A length-only finding
error now spends the existing second semantic read on a concise source-grounded
finding, with the complete pages and original question still supplied. Literal
quotes are checked again. Repeated overflow remains failed; there is no text
truncation, larger schema limit or extra unbounded model call.

Initial briefing selection also reserves space for supplementary qualifications:
one slot per saved source check, up to the existing four-addition contract. The
overall seven-item limit stays unchanged. If an initial draft exceeds its
remaining capacity, the model selects the material findings before any items
are locked; the audit preserves selected and discarded candidate indices.
Targeted item repairs cannot consume reserved slots. Independent integration
can therefore add a necessary qualification without changing accepted findings
or pretending an omitted risk is covered simply because the briefing is full.

Assurance validation now recognizes both `31 October 2024` and `October 31,
2024` as complete dates instead of treating the day-first spelling as a bare
year. Duration-period clarification uses the same calendar parser. Impossible
dates fail validation; different days and unmarked columns cannot borrow an
assurance label from another column. This does not override the independent
semantic review or authorize an unknown source status.

## Verification and limits

The initial `.256` layout-only measurement completed at 20 pages: 19 body pages,
one Data Index, five introduction pages and nine analysis pages. All configured
page-budget checks pass. The private layout diagnostic renders all 20 pages
with no automated visual issues; the formerly failing chart was also inspected
visually. Protected input fields remain identical. Private diagnostics are in
ignored `output/v168-256`, including `layout_audit.json`.

That diagnostic preserved the original checkpoint as `partial`. Its rejected
executive-brief draft applied an unaudited label without uniformly supported
source-column qualifications; that draft was never accepted or force-exported.

The subsequent user-authorized report replay used the configured DeepSeek
gateway, verified the PDF hash, and checked that the v166 extraction and numeric
analysis contracts equal the current contracts before explicitly migrating a
copy for report-stage recovery. The application's stale-checkpoint gate remains
unchanged. Document, observations, analysis plan and computed results are
identical to the original `.256` input.

The final analysis is complete, with six source-checked briefing items, 473
candidate-series decisions and accepted independent dispositions for both
supplementary source checks. Rejected drafts remain in the audit. The normal
PowerPoint exporter (without force) produces 19 slides: 18 body pages and one
Data Index, containing 17 native charts and two native tables. All three user
page-budget checks are satisfied. All 19 slides were locally rendered and
visually inspected; the automated visual gate reports no issues and identical
input/output content hashes. Display text is English throughout. Preflight has
one nonblocking template warning because the Data Index follows the official
Thank You page; there are no blocking financial or geometry errors.

Final private artifacts and audits are in ignored `output/v168-256`, including
`analysis_data_v168_256.json`, `analysis_presentation_v168_256.pptx`,
`export_audit.json`, `final_audit.json`, and `export-render-1`. These checks cover
the retained analysis scope and explicitly bounded supplementary pages; they do
not certify inspection of every page of the source PDF.

The previous `.848` result was also measured again: all 21 slides retain exactly
the same native shape geometry, display text, chart values and table cells as
the delivered v167 deck. Regression tests cover isolated and split compositions,
complete authored copy and notes, exact chart values, and rollback when the
bounded retry cannot fit. Additional tests cover exact calendar-date binding,
failed source-read recovery and history, bounded semantic shortening, and
initial briefing capacity reserved for independent source integration.
The final full suite passed **5,192 tests**, with 14 skipped and four existing
dependency/runtime warnings (`output/pytest-v168-verified.log`).
