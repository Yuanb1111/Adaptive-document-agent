# v212: audit quote roles and unfinished draft resumption

The v211 diagnostic ending `.209` failed in `report_audit_scope`. The final
three-binding draft quoted a literal seven-character printed page marker in
`scope_evidence`. The shared prose quotation schema required eight characters,
so the otherwise source-valid correction could not reach independent review
within the existing three-draft limit. The introduction had completed.

Audit scope evidence now accepts short printed markers only when their syntax
and a complete standalone line on the cited original page validate. Complete
scope prose and the reviewer's independent covered-counterpart proof remain
mandatory. The raw marker is preserved without padding or expanding it.

Real-provider validation also exposed the same length mismatch for complete
unit declarations. Writer and reviewer unit quotes now accept nonempty short
unit labels. Literal source presence, scale, currency, signed amount and exact
counterpart ownership checks are unchanged. Row and header prose retain their
existing schema limits. Row-field descriptions and format-correction feedback
explicitly require both the measure label and signed amount; an isolated amount
or fabricated label remains invalid.

A reporting retry can now retain the latest unfinished proposal from an
identical source/target context. It revalidates a saved draft or complete
schema-rejected response under the current schema and all binding checks,
then enters a **fresh independent model review**. It never reuses a rejected
review, malformed reviewer response, truncated draft, superseded proposal or
stale context. This proposal occupies the first slot of the existing bounded
three-draft cycle. A substantive rejection still requires a writer correction
and another independent review; nothing is automatically marked audited or
converted to unknown. Completed batches retain their existing revalidation path.

Further real validation exposed an unsupported summary-to-appendix assurance
link. Page-label repair now explicitly permits the reviewer to reject that
binding when the actual printed page is outside the range. Range failures
identify the physical page, proposed printed label and claimed endpoints, and
instruct the writer to find an exact covered counterpart or justify an unknown
disposition. Python does not assign assurance or select a semantic substitute.

All model requests still use `LLMGateway`, including fresh review of retained
proposals. `AuditScopeDraft` and `AuditScopeReview` now preserve provider-default
reasoning: they establish source ownership rather than format already validated
copy. The same-model comparison on the last failed group passed with two calls
in 64.4 seconds after several reduced-reasoning attempts failed. Other writing,
navigation and layout reductions are unchanged. Provider/model selection,
Local Only enforcement, extraction-v23,
analysis-v88, correction limits and source preservation are unchanged. Private
diagnostics, response logs and generated artifacts remain outside Git.

The first report continuation passed audit and budget-scope selection, then
failed briefing evidence checks. Its reduced-reasoning meaning reviewer demanded
an unaudited qualifier on the next interim column even though the supplied
inventory bound it only to the comparative column. The writer followed that
incorrect correction; the existing column check rejected it. `BriefMeaningReview`
now also preserves provider-default reasoning. Brief writing and repair remain
lightweight; no assertion or source-column gate is relaxed.

## Validation

Synthetic regressions cover short markers and units, unchanged quote text,
nonliteral/inline/wrong-page markers, empty evidence, scale/currency mismatch,
independent coverage rejection, the actual three-draft control flow, stale and
rejected checkpoint exclusion, source preservation, and bounded review repair.
The final audit, reasoning, gateway, privacy and checkpoint regression selection
passes **607 tests**, with five optional historical-checkpoint cases skipped
because their external input files are not configured. `git diff --check` passes.
After the briefing-review policy change, **261 focused tests** pass across
reasoning, source meaning, assurance scope, repairs and compound comparisons.
These selections overlap and their counts must not be added.

Offline revalidation of `.209` preserves all four completed batches and makes
its original final three-binding draft pass current schema and source checks.
This alone supplies no semantic approval.

Real-provider validation records every failed attempt separately. Regenerating
unfinished drafts exposed additional wrong-row/header proposals; retaining the
original source-valid correction subsequently passed fresh independent review
for those three amounts. The remaining scope group passed under provider-default
reasoning, yielding a complete source-bound audit with ten accepted amount
bindings and independently reviewed unknown dispositions. All document pages,
observations and calculated results remain equal to the original checkpoint.
The subsequent real-provider report continuation passed budgeting, briefing,
supplementary source review, language preparation and completion gates, then
exported a 20-slide PowerPoint. It used 20 physical model calls in 603.7 seconds.
Strict local rendering QA passed on its first attempt with no reported issues,
no repairs, and facts preserved. This validates continuation from the retained
extraction, calculations and validated plan; it is not a fresh full-PDF run.
The final saved checkpoint has no failed stage, and its document, observations
and calculated results remain equal to `.209`. Local rendering QA does not
certify PowerPoint/Google Slides parity or aesthetic quality.

## CI follow-up

The first v212 push exposed three stale assertions in the full Linux suite on
both Python 3.11 and 3.12 (6117 passed, three failed, seven skipped). The earlier
focused regression selections did not include these tests. They still expected
`BriefMeaningReview` to disable reasoning. The follow-up aligns the historical
direction, customization and editorial-scheduling tests with the v212 policy:
source meaning preserves provider defaults under either editorial setting,
while `BriefClaimDirectionReview` retains its configured reduction and route
guards. Runtime behavior and evidence gates are unchanged. All 92 tests in
these three files plus the audit reasoning regression file pass locally.
