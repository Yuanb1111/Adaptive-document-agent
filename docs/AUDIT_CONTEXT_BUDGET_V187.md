# Audit context budgeting (v187)

The private `analysis_data4.json` run stopped at `report_audit_scope` before any
audit-source discovery or binding request. It contained 63 target observations
and 20 complete source pages. The local aggregate ledger serialized to 160,951
characters and triggered a 150,000-character single-request guard, even though
the existing transport reviews only three targets per request. Its 21 actual
base requests each fit the same limit; the largest is 75,879 characters.

## Fix

The aggregate context remains the complete local evidence and accounting ledger.
The capacity guard now measures the existing `batch_targets` / `batch_context`
requests, including their scope text and full shared source/check evidence.
The 150,000-character limit and three-target batch size are unchanged. No pages,
target observations, headers or qualifications are shortened or removed.

Source discovery's remaining page allowance is computed from the largest real
batch, rather than the aggregate ledger. Its own complete navigation request
retains its separate 260,000-character guard. Expanded contexts, including model
selection metadata, must fit every review batch before use. An oversized actual
batch fails before model requests; its aggregate size, largest batch size, target
count and page count are retained in `report_audit_scope_unresolved` diagnostics.

All targets still require an independently accepted binding or explicit unknown
disposition. One rejected batch still prevents aggregate acceptance. Complete
approved batches remain resumable, and changing source text invalidates prior
discovery and acceptance. Model access still uses the gateway and existing
privacy controls. No new retry budget or document-specific routing is added.

## Verification

Seven new regressions exercise a 63-target aggregate above the old limit through
all 21 draft/review pairs, exact source preservation, unchanged approval reuse,
correct discovery allowance, oversized sources and single targets, oversized
new page selections, failed-batch recovery and stale-source rejection.

Audit, source discovery, briefing, reporting, budget, privacy, coverage and
introduction regression suite: **1,022 passed, 5 skipped**. Compilation and
`git diff --check` pass as well.

Read-only private replay:

```powershell
python scripts/replay_audit_context.py C:\Users\22767\Desktop\analysis_data4.json
```

Observed base context: 160,951 characters locally, largest request 75,879,
navigation request 252,033 (limit 260,000), and 74,121 characters remaining before
selection metadata and added pages. Full selected contexts are remeasured.

This verifies request construction and preserves all semantic gates. It does
not manufacture an audit verdict or establish successful PowerPoint export.
The local environment has no configured provider API key, so a live remaining
reporting run was not executed here. Private analysis files are not committed.

Only `PIPELINE_VERSION` changes; extraction and analysis cache versions remain.
