# v125: introduction evidence and bounded recovery

Two independent introduction failures were reported at the same progress
checkpoint. The v122 diagnostic rejected `summary_ranges.0.reason` for string
length even after structured-output repair. The v123 diagnostic failed after
classifying two literal blank lines as substantive Summary content without
supporting facts. Repeating the semantic reading preserved the same invalid
classification and could not produce evidence for whitespace.

The 66% display is a fixed candidate-generation progress checkpoint. A parallel
introduction failure is collected there before scoring starts; it does not mean
that PowerPoint rendering reached two thirds of the slides. Both diagnostics
contained no presentation plan and reported `INTRODUCTION_VERIFICATION_FAILED`.

Source-range reasons are now retained as internal audit metadata without a
slide-copy character limit. Gateway output budgets still bound generation.
Empty reasons and invalid or unavailable page ranges remain rejected. No reason
is truncated, and no missing source range is inferred.

Layout reconciliation can reclassify a model-assigned part only when its valid
source range contains literal whitespace, its retained text exactly matches
those source lines, and it contains no facts. The source text, page and line
ownership remain unchanged; the original role, title and reading explanation
remain in the audit. Nonblank source content, out-of-range references and facts
are not discarded by this rule.

## Validation

- The focused introduction and line-recovery tests passed: 50 tests.
- Offline replay of the original v123 diagnostic used its saved model responses
  and source blocks, without sending data to a provider. All 12 reading batches
  passed, covering 204 parts across source pages 10–32. Full-source ownership and
  evidence validation reported no reading errors.
- The v122 diagnostic did not retain the invalid range-selection response.
  Its exact raw response therefore cannot be replayed. The regression exercises
  the reported schema path with a long retained reason and separately confirms
  rejection of invalid page ranges and empty reasons.

These reading checks do not themselves establish successful final PowerPoint
generation. Full PDF acceptance is recorded separately after export verification.

## v124 diagnostic and additional acceptance failures

The v124 ROKAE diagnostic failed at the same checkpoint with two independent
source-check errors. Its generated Chinese month/year dates were compared as
bare numbers against English month names. Date support now binds the complete
month/year pair to the exact cited passage; it never authorizes a month digit as
an unrelated count or a fabricated full date.

The quoted offering table also separated `HK$9,945.6` from `million`, with a
left-column label interposed in flattened text. The parser now retains literal
line boxes inside the existing raw blocks. A narrow evidence adapter recognizes
an explicitly currency-tagged amount and a unique, immediately wrapped scale in
the same geometric column. Both must occur in the cited excerpt. Conflicting
amounts, unmatched columns, uncited units and ambiguous aggregate boxes remain
unsupported. Raw text, coefficients and currency are unchanged. Document parsing
cache v3 and extraction v16 invalidate results without the line evidence and
the corrected literal-duration typing described below.

Both original rejected ROKAE paragraphs pass offline validation against the
original PDF and saved text, without rewriting their claims. Unbudgeted themes
now use the same explicitly addressed paragraph repair as budgeted synthesis;
accepted surroundings are preserved. Invalid or unchanged patches stop with the
original unresolved checks instead of restarting whole-draft generation.

Real UBTECH acceptance exposed a separate semantic mapping request that exhausted
65,536 tokens on reasoning without any JSON. Semantic responses are now bounded
at 12,000 tokens. Only confirmed output-limit failures split the assigned terms,
at most twice, retaining full vocabulary, evidence context and original order.
Split recovery has its own gateway operation and respects the existing reduced
reasoning setting and provider-default opt-out. All model access, privacy,
transport, caching and usage tracking remain in LLMGateway. Other error types do
not trigger splitting; no partial successful result is returned on failure.

A later UBTECH reading response also assigned a broad passage and a narrower
boundary topic to overlapping lines, although their actual fact quotes were
disjoint. After the model's correction attempt, ownership reconciliation can
trim only that redundant prefix/suffix: both model-selected topics and every
fact remain, every quote must remain inside its own new range, and the exact
source-line union is unchanged. Interior/crossing/identical overlaps and empty
facts are not automatically repaired. The original parts remain in the audit.
Offline replay of all saved batches, plus the saved response for the separately
requested missing footer, passed 226 parts over all 23 Summary pages with zero
reading errors. No footer classification or substantive fact was invented.

The final full automated suite passed: 3,604 tests, 8 skipped. Existing LiteLLM
event-loop/deprecation warnings remain. The suite covers evidence boundaries,
provider/privacy isolation, content/format/pagination separation, source checks,
and the new targeted recovery paths. Actual PDF export and browser download
acceptance are still separate requirements, recorded below when complete.
The final run also includes the lexical boundary preventing `non-negative`
from being tokenized as `negative` and the rotated-page evidence regressions.

UBTECH's mixed ratio table exposed an additional literal unit case: `(%)` is
attached to each percentage row, while columns contain years and other rows
contain ratios in times. Evidence checks now recognize complete, exactly quoted
source rows with an explicit percent marker and numeric cells. Flattened quote
chunks retain the original source-line boundary. Bare values, unquoted rows and
unmarked ratios do not receive inferred percentage units.

Coverage repair previously received a generic parallel-series error and could
repeat the same periodless evidence under a new topic title. The validator now
reports every invalid selected series and the exact missing requirement, such
as a source-bound period. The repair request requires an explicit evidence
limitation decision for ineligible evidence; a caveat cannot invent metadata.
The same structural validation remains in force.

The next coverage batch exposed a false mismatch between a source row label and
the same label with its explicit raw unit appended in parentheses. Coverage
binding now removes only a suffix exactly matching that observation's retained
raw unit; all value, period, currency, scale, category, audit and definition
attributes must still match. Other qualifiers and generic totals remain
ineligible for automatic corroboration. The saved rejected review passes this
binding unchanged, with its original previous selection and all inclusion
decisions retained. Source observation IDs and raw row labels are unchanged.

The full introduction repair also returned an identical replacement twice for
one paragraph addressing multiple review findings. Patch application now treats
byte-equivalent parsed replacement content and title edits as idempotent; a
different text, fact ID list or title for the same address still fails. Empty
and unchanged patches still fail, additions are not silently deduplicated, and
the complete original model patch remains in the audit. Content evidence,
pagination and semantic review continue after applying the correction.

Further end-to-end verification found that the extractor's legacy `cash`
keyword overrode literal compact duration headers such as `6M2023`, creating a
balance-sheet date that the source had not supplied. Compact duration headers
now have the same priority as the existing written `months ended` flow headers;
an explicit `as of`/`as at` qualifier still prevents that flow classification.
Raw periods and values remain unchanged, and extraction cache v17 invalidates
the incorrect typing.

For quoted grids absent from the parsed table model, a narrow adapter recognizes
a complete repeated uniform currency-unit row (for example, `RMB’000` in every
column) and complete numeric rows of that exact width. Mixed units, percentages,
uncited headers, incomplete rows and unrelated subsequent prose cannot borrow
that unit. Accounting signs remain signed; repair feedback identifies the exact
opposite signed source value instead of reporting a generic unit mismatch.
Literal `negative` immediately before a currency amount is recognized as an
explicit sign, without inferring signs from metric names such as loss.

Identical paragraph text with exactly the same fact IDs within one logical
group is reconciled before pagination, retaining the removed item in the audit.
Different copy, evidence or logical groups are not merged. This handles a repair
that restates an existing paragraph under another label without hiding missing
coverage; full source and meaning review still follows.

An additional source correction is permitted only when the remaining atomic
source failures are a strict subset of the preceding failures. Introducing a
different failed value, repeating the same draft or making no progress still
stops; the overall five-candidate budget remains unchanged. Unsupported rounded
amounts now include a unique exact quoted quantity candidate in repair feedback
when Python can prove that numeric relationship. This is a correction hint,
not permission to accept rounded or sign-changed claims, and the model must
confirm its meaning in the retained source before using it.

UBTECH's sideways gross-profit grid exposed a separate extraction boundary:
the literal geometry had seven header rows, but analytical reconstruction
rescanned only four and classified the alternating percentage columns as
currency amounts. Geometry-backed tables now pass their actual header count
to reconstruction. Introductory reading uses the same decoded source geometry
for pages dominated by rotated text, retaining each other text orientation,
the original flattened extraction in `raw_text`, and the applied rotation.
This makes the complete literal rows available for existing quote-bound unit
checks without borrowing values across columns. Document cache v4 and
extraction cache v17 invalidate older flattened readings and column roles.
Synthetic PDF regressions cover 90/180/270-degree text, unrotated footers,
deep header tiers, incorrect currency/scales, swapped percentage/amount columns
and incomplete citations. The original physical page 23 now binds its total
gross profit and margin coefficients to the correct source units.

The next full run passed numeric checks but exposed repeated-review drift:
all seven newly rejected parts in the second and third reviews had exactly
the same source, copy and bindings as when the preceding reviewer accepted
them. An invocation-local ledger now retains only independent acceptances
whose complete part source and assigned rendered items (including text,
labels, titles, placement, references and quotes) have identical signatures.
Every changed binding and every unaccepted part receives a fresh review.
Opening and identity are always reviewed against the current rendered target.
The final audit combines the bound verdicts and retains their originating
attempts; source validation, full part coverage and the final deck digest
remain mandatory. This avoids reopening unchanged approved copy without
silently converting a rejection into acceptance or increasing retry budgets.

Targeted source re-reading also keeps its explicit scope: proposals wholly
inside already accepted source ownership are recorded and ignored, while the
original accepted facts remain unchanged. Requested ranges must still be
complete, and boundary-crossing/unknown/unowned spans still fail. A replay of
the rejected real batch now succeeds with all 29 parts retained and two
out-of-scope proposals quarantined. Quantity diagnostics use stable ordering
so set iteration does not change otherwise identical model repair requests.

## ROKAE full acceptance

The authorized DeepSeek run completed on the original 432-page PDF. It generated
61 slides: 17 body slides and 44 appendix slides. All 49 required Summary parts
from source pages 9–18 are exported; the analytical coverage review completed
with zero unreviewed series and editorial status `ready`.

The production deliverables UI exported and downloaded the PowerPoint through
the browser as `analysis_presentation (77).pptx`. The downloaded file passed ZIP
integrity and python-pptx reopening, and matched the CLI export's slide text,
shape geometry, native chart values, tables and body/appendix placement. All 61
slides were rendered and visually inspected. The final local artifact is
`output/v125/ROKAE-verified-v125.pptx` (930,576 bytes), SHA-256
`0fb54c1d14be3810d397b2b30c024a706507331075ab1bb7c4525b6fac7ad941`.
No native Microsoft PowerPoint application test was performed. Source evidence
limitations remain visible where appropriate; they are not hidden by disabling
checks. Private source files, model responses and generated decks are excluded
from the repository commit.

After the subsequent period/unit/copy fixes, a fresh export passed evidence,
financial and rendered-layout checks again. The existing browser download
matched this final-code export's complete text, geometry, charts, tables and
placements without any content difference.

A signed table coefficient no longer deletes a separately quoted explicit
quantity with the same digits. For example, a source paragraph may literally
describe a gross loss margin of 6.6% while its table uses (6.6). Only complete
nonparenthesized typed quotations survive the sign filter; an unsigned table
claim still cannot borrow their currency, scale or percentage unit. Regression
tests cover the actual mixed narrative/table case, incorrect signs, missing
citations and different units/currencies.

A final takeaway retry exposed a separate target mismatch: the generated body
was corrected, but a long takeaway caused the original invalid topic title to
remain on the slide. Recovery now asks for and validates both title and takeaway
as one candidate, without changing the selected question, observations or source
series. A title-only correction is distinct from a repeated rejected draft;
failed candidates leave both original fields unchanged. Follow-up errors are
scoped to the affected topic so unrelated withheld claims cannot redirect its
repair. Synthetic regressions cover successful title-only repair and atomic
rejection of a still-invalid replacement title.

A subsequent full run selected a different valid narrative and exposed a
coverage retry ambiguity. The model described two equal-valued source views as
included although their exact source definitions were not selected. Repair
feedback now includes every scope field used by exact binding (including parent
section, period type, validation status and anomalies) and enumerates the
unbound series IDs. The model must explicitly select those IDs or author an
omission reason; judging a different definition analytically redundant cannot
stand in for structural inclusion. Exact evidence validation and bounded retry
limits remain unchanged. The source analysis checkpoint can be reused to run
this production coverage stage and all downstream export checks while retaining
the already independently verified introduction and calculations.

The real withheld-claim replay also exposed two numeric-gate inconsistencies.
Topic selection now recognizes a literal percentage coefficient when its
retained unit metadata is percentage, matching the existing slide validator.
An untyped count still cannot borrow a percent sign. A separate adapter ignores
parenthesized annotation digits only within a literal retained source metric
label (including its display form without a list bullet). It never authorizes
those digits as an unrelated amount, and original source labels and semantic
claim text remain unchanged. This repairs generated chart headings such as a
metric with a source footnote while preserving unsupported-number rejection.

The final source-label bullet adjustment passed 29 focused topic, coverage and
repair regressions after the full suite above. Replaying the actual newly
selected topics and regenerated charts now passes the previously failing
presentation compiler. The two originally withheld UBTECH conclusions both
passed real gateway repair with corrected titles and takeaways; neither claim
was hidden or replaced by its question to achieve this result.

## UBTECH final acceptance

The authorized run processed the original 776-page PDF. Final acceptance resumed
its complete analysis checkpoint, preserving the extracted observations,
calculations, independently verified introduction and selected narrative. Both
withheld conclusions were repaired through the real LLM gateway, then the
production editorial and export checks ran again. This was checkpoint recovery,
not a second clean end-to-end run with the final code.

The final report has editorial status `ready`, zero withheld topics and no
pending analytical coverage review. It exports all 104 required substantive
Summary parts from physical pages 10–32. Its 64 slides comprise 17 body slides
and 47 appendix slides. The rendered layout gate passed with zero issues and
facts preserved.

The production deliverables UI generated and downloaded
`analysis_presentation (78).pptx`. ZIP integrity and python-pptx reopening passed;
all slide text, shape geometry, native chart values, tables and body/appendix
placement matched the verified CLI export. The final artifact is
`output/v125/UBTECH-verified-v125.pptx` (1,081,794 bytes), SHA-256
`8088a4694d8097493f2bcbe36d6f1bb601f642f4a9459370d0a5fc578d222f1f`.

All 64 final slides were rendered. Nine changed slides were visually inspected
again; the other 55 were pixel-identical to the already inspected render.
Browser download proof was captured in `output/v125/ubtech-download-verified.jpg`.
No native Microsoft PowerPoint application test was performed. The original
PDF, private checkpoints, generated deck and screenshots remain excluded from
the commit. A final ROKAE re-export after the shared numeric fixes also matched
its previously downloaded file without content or layout differences.
