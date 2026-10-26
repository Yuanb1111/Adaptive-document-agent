# Audit batch rationale and feedback v196

The v195 diagnostic ending `.148` stopped in `report_audit_scope`. Five batches
completed. One batch's reviewer returned valid JSON with `verdicts=[]` and a
substantive rejection of its three unknown dispositions, but `unresolved_reason`
was 1,453 characters against a 1,400-character schema limit. Its output correction
returned 1,450 characters and failed the same constraint.

The repair feedback contained only `Bounded response failed schema validation`,
the original text and ID-ledger constraints. It omitted the actual Pydantic field
path and length limit, so the reviewer had no targeted diagnosis. No corrected
draft was reached in that batch.

## Changes

The shared draft/review unknown rationale now has a maximum of 4,200 characters:
the three-target batch bound times the existing 1,400-character per-target reason
allowance. Individual binding and verdict reasons retain their 1,400 limit. This
is bounded response-schema capacity, not additional requests or higher token
limits. Full rationale text and semantic verdicts are retained without truncation,
rewriting or inferred approval.

Reviewer output correction now uses the existing `schema_feedback` mechanism,
which revalidates complete output and supplies exact field paths, error types and
limits, excluding duplicate input bodies. The prompt explains how to shorten an
overlong reason without changing its verdict, scope or material qualifications.
Repeated output failure remains terminal, with concise field-level diagnostics
also included in the surfaced error. Refusal, truncation, transport and privacy
failures remain distinct and do not gain new repair routes.

The failed batch also exposed a semantic disagreement: a retained observation
used a parent metric name while its category and literal evidence row named a
component. Both draft and review instructions now require the complete retained
identity: metric labels, dimensions, category dimensions, parent section and
source row. A broad metric label alone neither proves a total nor invalidates an
otherwise supported component. The model must establish the same exact component
from original source evidence; matching numbers alone remain insufficient. No
observation is renamed and no value, category or period is changed. A genuine
source conflict must remain explicitly unresolved.

The response-schema change expires old transport-capacity failure identities.
Completed source approvals remain reusable only after their exact fingerprint,
binding and independent counterpart proof are revalidated. Acceptance and retry
contracts, source gates and gateway/privacy enforcement are unchanged.

## Replay and limits

```text
python scripts/replay_audit_scope.py path/to/analysis_data.json --review-schema-path
```

Both complete recorded `.148` reviewer responses now satisfy the schema, with
their full rejection reasons unchanged. Replaying the first through the real
controller reaches `AuditScopeDraft -> AuditScopeReview -> AuditScopeDraft`:
the source disagreement is delivered to a new writer request, consuming zero
review-output corrections. All five completed batches revalidate successfully.

The replay stops at that missing writer response. It neither invents a corrected
binding nor grants assurance, makes no provider calls, and does not establish
end-to-end analysis success. Private diagnostics remain outside the repository.

Tests cover recorded-length boundaries, the finite batch limit, exact length-error
feedback, repeated failure, preserved substantive rejection, category-aware
binding without observation mutation and mandatory independent approval.
The pipeline becomes v196; extraction and analysis versions remain unchanged.

Validation: 1,214 related audit, briefing, gateway/reasoning and cache tests pass.
The final field-level error-message change also passes 19 focused tests. Python
syntax checks and `git diff --check` pass.
