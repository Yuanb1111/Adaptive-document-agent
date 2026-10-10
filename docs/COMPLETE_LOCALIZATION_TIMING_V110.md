# Complete localization and observable timing, v110

## Problem and resulting behavior

The latest private custom run, PPT70 / analysis90, used v108. It exported a
160-slide deck with incomplete checked Chinese copy and no executive brief.
The pipeline took 1,466,686 ms; export took another 165,675 ms. Translation
and its independent review occupied 377,991 ms of elapsed time, including
125 seconds of model request latency. Local geometry scanning and intervening
processing accounted for much of the difference. These are observations from
the original run, not estimates for v110.

Introductory claims had been split for layout before translation. Some parts
therefore ended inside a date, amount or sentence, making individually faithful
translation impossible. Whole claims are now reconstructed by their retained
continuation groups. Accepted translations are paginated before export, with
every original part and evidence locator still verified against visible native
text. Exact already-Chinese text is retained without another model request.
Source table cells, raw values, original quotations and notes remain literal.

Explicit currency/scale quantities use protected transport tokens. Python
restores the exact coefficient, sign and decimal spelling with equivalent unit
labels; it never rescales a quantity. Independent semantic review examines the
restored prose. Repeated shared dates, yearless month/day headers and Chinese
parentheses preserve precision; invented dates, lost signs and rescaling fail.
Reflowed numbering and continuation markers compose only exact checked base
labels, retain their ordinals, and participate in final coverage verification.

The immutable copy inventory builds its geometry index once. Independent
introductory editorial batches run within existing gateway admission limits,
merge in source order and retain per-batch audits. Only editorial planning over
validated reading facts receives the existing optional reasoning reduction;
source reading and meaning review retain their previous reasoning policy.

Brief meaning review can return item-scoped literal evidence references instead
of repeating lengthy tables. Python resolves references and still validates
each endpoint, unit, comparison direction and reporting duration. One format
correction is allowed. If a replacement remains unreviewable or rejected, it
cannot displace an independently verified finding. The surviving brief must
still satisfy its item-count, quotation, quantity and selected-topic gates.
Privacy violations and transport failures retain their established behavior.

## Timing records

The final result explicitly synchronizes timing dictionaries after customization
finishes, avoiding the earlier Pydantic dictionary-copy omission. Foreground
records include source-chart inventory, identity wait, background drain and
customization review. Nested details include content review, localization copy
inventory, translation requests, geometry adaptation, independent review,
validation and final requirement checks. Failed model requests are timed too.
Introductory reading, editorial wall time and each editorial batch are retained;
background brief review timings are copied back to the exported result.

`pipeline_total_ms` is elapsed pipeline wall time. Export wall time is separate.
Nested and background intervals overlap and must not be added to their parents.
`foreground_uninstrumented` exposes the remaining foreground accounting gap.
Progress reports the active translation batch and repair attempt; percentages
remain workflow milestones, not a prediction of remaining time.

## Regression and acceptance boundary

Validation uses the private PPT70 / analysis90 inputs, stored model responses,
explicit corrected Chinese fixture translations and local native export. The
source artifacts and generated regressions stay in ignored `tmp/` and `output/`;
they are not committed or sent to a model provider. Reviewer acceptance in an
offline translation fixture is not evidence of fresh model semantic quality.

The brief replay reproduces the original candidate/patch sequence and a repeated
review format failure. It retains three originally verified findings, rejects
the wrong debt-definition claim and unreviewed replacements, and meets the
original five-topic coverage gate. Tests also require rejection when filtering
would lose mandatory topic coverage or leave fewer than two findings.

The custom export regression verifies all 62 substantive Summary parts, 108
whole claims and 155 original evidence slots. Every retained source-table cell,
header and footnote is compared through the existing editable-table export
gate. The final fixture deck contains 152 slides, retains 38 source-table
fragments and 30 visible footnotes, and has no display string outside its
checked translation bindings. Literal source grids compare equal before and
after export. Clause boundaries are preferred over arbitrary cuts inside
names, amounts and dates; concatenated copy must still match the complete
checked claim. Existing reviewed Chinese fixture paragraphs are reused for
source-language reading extracts; newly corrected fixture copy is explicitly
offline, including the Chinese executive-brief heading.

The full local suite passed **3,324 tests**, with **8 skipped**, in 380.789
seconds (`tmp/v110_complete_results.xml`). Additional focused regressions verify
late unit-word and clause-boundary changes. Local rendering of all 152 pages
reported no visual-QA issues; representative introduction, period/amount,
briefing and appendix pages were also inspected visually. These rendering
checks do not replace semantic acceptance of fresh model-generated claims.

An 80-string local geometry sample on PPT70 took 30,868 ms using repeated
whole-deck scans and 652 ms using the cached index, including its initial
construction. This measures local text-box lookup/adaptation only. It excludes
inventory construction, model requests and export, and does not predict a
fresh run's total latency. The fixture translation replay used six batches
with no failed retry; already-Chinese copy and compact references reduce
avoidable requests without relaxing source or meaning checks.

A fresh default and Chinese custom model run remains necessary to measure
actual end-to-end latency, semantic output quality and independent completeness
of PDF table detection. Source-fragment preservation proves retained cells are
not lost; it does not certify that digital extraction detected every PDF table.
