# Typed percentage validation (v159)

The v158 run ending `.874` completed introduction and coverage review, then failed
while measuring the native presentation. Theme validation rejected six percentages
whose numeric cells omitted `%` because the source header already supplied that
unit. Slide validation accepted these same source-typed values. No source values
were missing from the retained product-mix evidence.

Theme and slide validation now share source numeric-field preparation. A numeric
cell licenses a percentage token only when its observation explicitly has unit
`percent` or unit family `percentage`. Each field is parsed separately to prevent
a grouped amount swallowing an adjacent year. Theme evidence ownership, unknown
values, calculation eligibility and source validation remain enforced. Rejection
messages include the unsupported numeric tokens.

Source-validated claim restoration keeps the complete takeaway in analytical and
summary copy while restoring model-authored topic labels in section and theme
headers. Existing headers are migrated only when they exactly equal the retained
takeaway. Other repaired wording is preserved. Budget-stage failures now retain
their component, exception type and message for the failure panel.

The extraction contract remains v23; the analysis contract advances to v83.
Restart the app to load v159. A new analysis uses the corrected validators.
Offline replay of `.874` checks the retained model decisions and original evidence;
it does not represent a fresh live-provider analysis or semantic approval.

Offline validation of the saved checkpoint passes the original percentage-bearing
plan, actual native budget refinement without model calls, and local export QA.
The deck has 20 body pages (5 introduction and 9 analysis) plus 1 Data Index page;
all 21 pages render with no automated QA issues. Retained observations, analysis
results, topic selection and LLM usage remain unchanged. The original partial
checkpoint is preserved; only the private diagnostic copy is exported.

Regression validation: 104 focused presentation tests passed, followed by the
complete suite with 5,054 passed, 14 skipped and four existing dependency warnings.
