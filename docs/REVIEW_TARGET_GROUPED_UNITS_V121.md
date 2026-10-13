# v121: generated-slide review and grouped unit evidence

The v120 failed run rejected a business introduction as though it were a PDF
cover. The generated opening already described the subject's business. Its
unchanged editorial retry could not correct a review aimed at the wrong object.

The reviewer now receives an explicit `opening_target` containing the first
generated slide after pagination. PDF identity pages are separately labelled.
Both accepting and rejecting verdicts must return that slide's ID and the exact
ordered paragraph texts. Missing, stale or source-page bindings trigger one
review-protocol repair with unchanged source and copy. Exhaustion fails closed
without invoking the editor. A correctly bound semantic rejection still reaches
editorial repair; repeated rejected copy still stops. Python verifies binding,
while the model continues to decide whether the introduction explains scope.
This binding reduces target confusion but does not guarantee model judgments.

Borderless extraction now recognizes compact `of2024` year cells and excludes
date-header fragments preceding year tiers from analytical rows. Centered unit
superheaders are mapped to numeric columns only when source geometry establishes
a unique contiguous partition. Count and percentage groups retain distinct
source headings. An incidental percent symbol no longer becomes a global table
unit. Half-year qualifiers require matching column geometry; missing geometry
leaves the period unresolved. Raw header lines, body values and page evidence
remain available. Extraction and analysis cache versions are bumped.

Offline replay of the supplied PDF through TableExtractor, TableReconstructor
and ObservationExtractor verifies page 245's 24 observations: eight count columns
and four percentage columns, including source-bound first-half periods. Page 264
has seven body rows with no ambiguous date-header rows; dates and year labels no
longer become observations. This replay does not constitute a new hosted model
run or acceptance of a complete generated deck.

Regression coverage includes wrong/missing/stale/incomplete opening bindings,
bounded protocol exhaustion, genuine semantic rejection and editorial correction,
grouped units, preserved raw values, no-geometry uncertainty, split date headers,
existing sparse-row guards, source coverage and presentation export tests.

Validation: the complete offline suite exited successfully with no failures and
eight environment/opt-in skips. The final header-guard and verdict variants were
also checked in a 66-test focused run, all passing. The supplied PDF replay was
repeated against the final extraction code. No hosted end-to-end rerun was made.
