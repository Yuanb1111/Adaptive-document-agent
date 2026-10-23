# Review capacity and stage timing (v182)

## Problem and change

A completed v181 run spent 20m55s in analysis and 34s exporting. Several
assurance/source-integration requests exhausted their output allowance, including
reasoning, and regenerated from the same complete evidence. The supplementary
source-review UI label had no stage identity, so its elapsed clock included
preceding briefing/budget work (about 8m40s displayed versus 2m40s for the review).

Start the affected requests at their former recovery allowance:

| Operation | Previous initial / recovery tokens | New initial / recovery tokens |
| --- | --- | --- |
| Audit scope draft | 12000 / 20000 | 20000 / 32000 |
| Audit scope independent review | 8192 / 16384 | 16384 / 24000 |
| Supplementary source draft and independent review | 8192 / 16384 | 16384 / 24000 |

Each still permits only one capacity retry after a proven `finish_reason=length`.
Larger allowances are ceilings, not required answer lengths; usage and latency
remain provider-dependent and can increase for an unusually long answer.
No model, reasoning setting, prompt, schema, source context, semantic correction
budget or independent-review acceptance rule changes. Partial responses remain
diagnostics only. LLMGateway privacy, admission limits and caching remain intact.
The audit capacity fingerprint includes the new limits; it expires historical
capacity failures while preserving correctly source-bound completed reviews.

Distinct workflow identities now time source audit qualifications, executive
briefing, supplementary source integration, requirement review and localization.
Audit entry emits an explicit event before discovery or batch work. Batch updates,
capacity retries, polling/restoration and unknown status details do not reset the
current stage. Total elapsed time and progress percentages retain their behavior.

## Validation and limits

Offline before/after tests simulate the same output requirements and compare
complete prompts, source facts, drafts, approvals and rejections. A successful
audit draft/review pair needs two requests instead of four; a supplementary
draft/review pair needs two instead of three. Semantic rejections still fail and
consume the same bounded correction budget. Existing tests cover exhausted
capacity, invalid formats, stale approvals, cancellation, privacy and checkpoints.

Clock tests use actual workflow callbacks and controlled time, including the
520-second inherited-clock regression, parallel batch status, refresh and failure.
Browser clock tests cover phase changes and stale callbacks independently.

Local validation: 65 focused tests passed; expanded audit, source, introduction,
LLM, pipeline, checkpoint and progress regressions passed 1434 tests with 11
environment/recorded-artifact skips. All 19 browser notification/clock tests
passed. GitHub CI runs the full suite on Python 3.11/3.12 with real LibreOffice.

These are deterministic request-count comparisons, not a live-model speed or
quality benchmark. The change targets avoidable replay; it does not promise a
fixed end-to-end runtime, remove reviews, or optimize unrelated semantic batching.
The next real document run is needed to measure actual latency improvement.
