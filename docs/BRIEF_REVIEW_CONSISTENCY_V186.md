# Briefing review consistency (v186)

The private `analysis_data3.json` run completed introduction and topic coverage
review, then failed while writing the deferred executive brief. It was incorrectly
reported as a physical presentation budget failure.

The saved responses expose three issues:

- The percentage gate required both endpoint percentages inside a qualitative
  heading, although they were explicitly stated in its own body and source table.
- The independent direction reviewer classified a loss-widening predicate and
  also listed that exact predicate as missing. It similarly classified a share
  clause as non-directional while reporting the same clause as an omitted change.
- Source-binding correction received a generic non-directional comparison error
  without the affected comparison index, exact claim or independent reason. Its
  corrected response retained comparisons inferred from separately dated facts.

## Changes

A qualitative heading may bind percentage endpoints explicitly present in the
same item's body and literal source evidence. Period labels remain possible.
Explicit currencies, units or bare endpoint coefficients cannot borrow percent
units through this exception; body fragments retain the original requirement.
The source reviewer must establish the same measure, periods and scope, and the
independent wording reviewer still checks the heading's actual direction.
Compound headings require separate bindings for different predicates/directions.

Overlapping covered/omitted predicates are inconsistent reviewer transport. They
use the existing one source-blind format correction, with the previous response
and exact diagnostic. Python does not remove omissions, classify language or
approve a claim. Persistent inconsistency fails closed. Source endpoints and
source verdicts are never supplied to that correction. Non-directional comparison
errors now identify the exact index, claim and reason for the existing one source
correction; no new recursive or additional correction budget is introduced.

Deferred briefing failures carry `FinalBudgetBriefError` and are reported as
`executive_brief` / `ExecutiveBrief`. Native measurement and export-budget errors
remain budget errors. Privacy and cancellation continue to propagate.

## Verification and limits

The new regression cases cover source-blind reconciliation, persistent failures,
real direction contradictions, precise source correction feedback, percentage
heading support and missing-unit/value/direction rejection, plus deferred-error
classification. Existing briefing, reporting, budget, privacy, coverage and
introduction regressions: **808 passed, 5 skipped**. The new v186 file contains
17 regression cases. Compilation and `git diff --check` also pass.

Read-only private replay:

```powershell
python scripts/replay_brief_review.py C:\Users\22767\Desktop\analysis_data3.json
```

The final saved source review previously rejected item 2 solely for heading
percentage support; the current source checks pass it using its original table
evidence. The last saved direction response now requests bounded reconciliation
instead of treating its own contradictory omission as an audience defect.
Other saved direction failures still require model correction and independent
verification. Replay does not generate a replacement model verdict, certify
semantic approval, or export a PowerPoint. A live reporting run remains necessary
to establish complete deck success. Private document contents are not committed.

Only `PIPELINE_VERSION` changes; extraction and analysis cache versions remain.
