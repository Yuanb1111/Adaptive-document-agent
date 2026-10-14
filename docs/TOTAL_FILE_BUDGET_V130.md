# Complete-file audience budget (v130)

The previous successful export contained 19 body slides and 42 appendix slides.
It passed the earlier body-only requirement, but 61 slides does not meet a request
for an entire file of approximately 20 slides. Reading every source paragraph
must not automatically create an audience slide for every paragraph or table.

The upload controls now default to a complete-file maximum of 20 physical slides,
an introduction maximum of 5, and an analysis maximum of 10. Cover, contents,
Data Index, Conclusion, closing and appendices all count. A separate optional
checkbox explicitly permits body-only accounting; it is off by default. Numeric
controls still bind directly to typed requirements before background editorial
work. Whole-file/body scope and analysis limits participate in retry validation.

## General Agent changes

The full introductory source remains read, owned by physical page and source
line, classified and validated. A model then selects the source parts needed to
explain the subject and essential context in a concise introduction. Selection
uses the actual source and purpose, with no issuer names, product models, document
types, heading lists or paragraph-length importance rules. Every substantive part
receives an include/omit decision with a specific reason. A separate model review
sees the complete source and all decisions and can reject omitted material
conditions, reporting scope or misleading positive-only selection.

The selection audit binds to a fingerprint of the complete reading. Missing,
duplicate, stale or independently rejected decisions fail. Source classifications
do not change: omitted substantive passages remain content in the audit, never
become layout/footer text. Selected parts must still pass numeric evidence checks,
independent part-meaning review and complete visible native-text verification
after PPT serialization. Legacy results without audience selection retain the
old complete-coverage contract.

Selection and its independent review retain configured provider reasoning and
use bounded output capacity. A truncated selection can be regenerated once
from the full original source with a higher output limit; incomplete JSON is
never accepted or used as evidence. Semantic repair also distinguishes unresolved
old issues from newly discovered issues in the same source part. A changed
failure reason does not prove progress: an independent comparison must confirm
that every prior rejected issue is actually corrected. Only then is one final
additive correction permitted. Existing text, titles, order and evidence IDs
are locked; source checks and independent meaning review still run afterwards.
Unchanged drafts, unresolved old issues and exhausted repair budgets fail.

Under a whole-file budget, chart-topic selection reserves physical capacity for
the introduction, source limitations, Data Index, Conclusion and closing. The
normal orchestrator also builds validated native objects before completion. If
their actual page counts exceed a requirement, a bounded model refinement sees
each topic's real physical cost and complete source evidence. It decides every
previously selected series once, can retain only original topic/evidence subsets,
and rewrites the questions and takeaways to match the retained scope. An
independent reviewer must accept the source meaning and omission reasons.
Python recompiles complete retained series, verifies unchanged extraction and
measures again, reserving space for the final briefing. That briefing is freshly
generated and independently checked against the final topics, then the complete
native deck must pass all three physical limits. At most two proposals are
allowed. Failure returns a partial reporting checkpoint, never a completed
over-budget result. No native slide is deleted to make the count pass.
Source wording correction uses its separate bounded topic operation. A final
briefing's source/meaning failure stops that stage; it is never fed back as a
reason to omit an analytical topic or its negative counterevidence.

The native export uses Data Index as navigation to selected analytical scopes with
literal source units, periods and PDF references. Complete selected raw records
remain in index notes, and the complete extraction remains in analysis/data
exports. Explicit chapter-wide table requests still render their full tables and
can produce an honest budget conflict; they are never silently truncated.
Continuations of the same model-authored topic share one source-index entry,
with the complete union of their periods, units, source pages and raw records.

The source-checked, independently reviewed Executive Brief appears once as the
final Conclusion, after charts and Data Index. Automatic duplicate Key Figures
and value-chain pages are not added in this mode. Short conclusions retain their
own section instead of being folded into a chart margin. The actual serialized
file must satisfy the total, introduction and analysis limits. Over-budget files
are refused; pages are not deleted or relabelled to manufacture compliance.

## Verification

Regression tests cover complete-reading retention, independent selection
rejection, stale/malformed selection, exact selected native bindings, numeric
claim rejection, physical appendix counting, analysis continuations, source-index
raw values, and the final Conclusion's order and visibility.
Additional tests exercise same-part residual failures, independent rejection of
claimed repair progress, preservation of the first correction, and mandatory
review of the final additive correction.
Declared magnitude quantities now tolerate only insignificant whitespace
differences in their complete displayed amount. The signed validation view is
temporary; source and displayed text remain unchanged. Duplicate matches,
changed digits, currencies, scales, signs and missing rate denominators remain
invalid, and an annotation for a positive magnitude cannot match an already
negative amount.

## Approved same-PDF validation

The existing DeepSeek configuration was used with the authorized PDF. The full
524-page extraction, retained calculations and source SHA stayed unchanged.
The introductory reading retained 62 substantive parts; 10 source parts were
selected with complete importance decisions and accepted independent review.
All 10 selected parts remained visibly bound after reopening the serialized PPT.

The final export is **18 physical slides**: cover 1, contents 1, introduction 4,
data/chart analysis 8, coverage/limits 1, Data Index 1, Conclusion 1, closing 1.
It contains no extra source-table or introduction appendix. The model's final
chart omissions and their independent review are recorded separately from the
unchanged extraction. A fresh final briefing retained 3 verified findings;
source/meaning failures for other candidate findings remain in the audit.

Financial QA has no critical errors and preflight passed. All 18 pages were
rendered locally, with visual status `passed`, no issues, no position repairs and
`facts_preserved=true`. An independent reopen rechecked actual total/introduction/
analysis counts, introduction bindings and the Data Index/Conclusion order, then
preserved all rendered previews for inspection. There were no force flags or
disabled validation checks. This does not certify Microsoft PowerPoint parity.

The final full regression run passed **3,752 tests**, with 8 skips and 4 existing
mocked LiteLLM/Windows event-loop warnings. The subsequent diagnostic-count change
passed 21 focused export/reliability tests and distinguishes physical from planned
counts rather than reporting 14 logical instructions as the file page count.

Ignored local evidence: `tmp/v130-shipping/analysis.json`, `verified.pptx`,
`visual-qa.json`, `export-diagnostics.json`, `structure.json`, `contact-sheet.png`,
`preview/`, plus `tmp/v130-shipping-tests.log` and `tmp/v130-native-reopen.log`.
