# Audit review after physical budget selection (v188)

The private V187 export stopped at `report_audit_scope` after an accepted physical
budget proposal introduced an audit qualification. The initial audit stage took
5 ms and retained no review or unresolved record. The saved original topics had
no audit caveats; the final plan required review of 16 unknown-status measures.
The final gate correctly rejected those unreviewed measures, but the pipeline
had never scheduled their review.

This was not another input-size failure. The saved final scope contains 15 full
source pages and six batches. Its largest request is 60,592 characters, below
the unchanged 150,000-character limit.

## Changes

- An independently accepted physical budget proposal now refreshes its exact
  audit scope before writing the final briefing. Rejected or oversized proposals
  do not receive an additional assurance review.
- A fitting native projection also checks for newly introduced scope. Fresh
  audit acceptance invalidates the earlier briefing; its replacement and audit
  notes are measured again. If they exceed the budget, ordinary model-owned
  selection uses those measured costs.
- Unchanged or reduced scopes reuse their valid accepted review. Changed source
  text or new targets still require fresh review. Every retained target needs
  an independently accepted binding or explicit unknown disposition.
- Audit failures are terminal for the budget operation. They cannot prompt
  another omission proposal. Candidate source discovery, completed batches and
  failure diagnostics remain available to reporting retries. Reporting errors
  retain the original audit error type and message.
- Final audit, source integration, topic coverage and physical export gates
  remain active. Extraction, raw values, page evidence and calculations are
  unchanged. Model calls still use the gateway and its existing privacy rules.

Only `PIPELINE_VERSION` changes; extraction and analysis cache versions remain.

## Verification

Twelve new synthetic regressions exercise the candidate review/briefing order,
terminal rejection, configuration/privacy failures, fitting-plan scope changes,
refreshed briefing geometry, unchanged/reduced acceptance reuse, stale sources,
preservation of successful audit work after a later briefing failure, and
preservation of the original failure at the orchestration boundary.

Audit, briefing, budget, reporting retry, gateway/privacy and source/topic
coverage regressions: **1,036 passed, 5 skipped**. Compilation and
`git diff --check` pass. A full-suite attempt was interrupted when Streamlit's
UI test blocked while creating the Python/Windows event loop's local
`socketpair`; an isolated run reproduced that sandbox limitation. The full
suite is therefore not reported as passing.

Read-only replay:

```powershell
python scripts/replay_audit_lifecycle.py C:\Users\22767\Desktop\analysis_data.json
```

The replay reports only scheduling and capacity metadata. It inspects saved
original topic caveats without reconstructing the historical plan, checks the
actual final targets, and verifies that refresh reaches `AuditSourceDiscovery`.
An offline gateway probe stops before model execution; it never manufactures a
missing response or an audit verdict. The input file remains unchanged.

This verifies the repaired scheduling path, not a live provider acceptance or
successful PowerPoint export. Private analysis data is not committed.
