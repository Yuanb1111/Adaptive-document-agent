# Audit period headers v193

The reported v192 diagnostic ending `.791` completed company introduction with
five body slides and independent semantic review. It then failed in
`report_audit_scope`, a later stage. Total recorded wall time was 1,264,363 ms;
the audit-scope stage occupied 615,768 ms. This was not another introduction
pagination failure.

Two audit batches exhausted their binding-validation correction on valid shared
date notation. One header shared `31 December` across `2021, 2022, 2023`; another
placed month/day tiers on separate lines above a year row. The validator only
recognized complete contiguous dates. Final recorded drafts contained four
date-header errors across the two batches.

Snapshot preflight now recognizes complete dates, explicit shared-year lists and
strict multiline date/year-only header tiers. It checks calendar validity and
literal components without inventing a period, rewriting source text or assigning
a table column. A flattened tiered header cannot establish which date owns a
particular amount: the independent model still must identify the exact original
table, amount column, unit, entity and covered assurance scope. Both drafting and
review instructions explicitly require complete literal headers and prohibit
cross-pairing years or substituting assurance prose for original table headers.
Literal quote, amount, unit, currency, counterpart-page and scope checks remain.

The audit operations made 17 provider calls, including three output truncations.
Their cumulative output usage was 217,488 tokens, of which 201,433 were reasoning
tokens. These are summed usage counts across concurrent requests, not wall time.
The two bounded audit operations now honor the existing `simple_task_reasoning`
setting: supported routes request reduced reasoning, while `provider_default`
opts out. Exact model/endpoint guards, Local Only enforcement, independent review,
full source context, output limits and correction budgets are unchanged. This
addresses the observed reasoning cost; live latency and acceptance are not proven
by offline tests.

Changed per-operation request identities invalidate the affected model responses
and transport-capacity failures. The common reasoning-policy version remains v9
so unrelated requests retain their cache identity. Existing approved audit batches
remain reusable only after their source fingerprints, bindings and independent
proofs are revalidated. The pipeline version becomes v193; extraction and analysis
cache contracts are unchanged.

## Offline verification

```text
python scripts/replay_audit_scope.py path/to/analysis_data.json
```

The script reads the diagnostic in place, makes no model calls, and prints only
validation counts and batch status. It revalidates the three completed `.791`
batches. Both failed final drafts now pass binding validation and reach the real
controller's independent-review boundary; the replay deliberately stops there.
The remaining batch has no complete recorded draft. No fresh approval is simulated,
and this is not an end-to-end successful analysis. No private diagnostic or source
document is copied into the repository.

Regression cases cover shared headers, unrelated years, invalid dates, explicit
date cross-pairing, required independent source proof, rejected semantic reviews,
raw-data preservation, wrong values/currencies, route capabilities, user opt-out,
unchanged output capacity and invalidation of only affected operation caches.

Validation: 569 audit, gateway/reasoning, cache-contract and v191/v192 layout
regression tests pass. Python syntax checks and `git diff --check` also pass.
