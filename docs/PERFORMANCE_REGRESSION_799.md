# Performance regression investigation: .799

## Evidence and scope

The October 22 `.028` run completed in 526.8 seconds (8m47s), and the
October 26 `.973` run completed in 693.4 seconds (11m33s). Matching local PPTX
exports exist. They and October 28 `.799` use the same 524-page PDF hash and
configured model. `.799` reached the 900-second spending deadline during
executive-brief review. None of these logs reports an application cache hit.
The earlier successful runs are real; a 15-minute deadline does not itself fix
the regression.

The selected evidence and work performed differ. Compared with `.028`, `.799`
spent approximately 4m35s versus 3m15s before reporting, 4m39s versus 2m55s
in reporting, and 1m22s versus 54s in presentation planning. Its separate
audit-scope stage took 2m24s. These stage values are diagnostic measurements,
not a universal performance guarantee. Nested/background timings should not
be summed as independent wall time.

`.799` has 86 recorded calls and 1,994,596 known input/output tokens versus
86 calls and 1,585,291 tokens in `.028`. It performs more candidate/insight and
topic-coverage work, plus exact audit review. v188 defers briefing until that
audit is available; v212 restored provider-default reasoning for audit draft,
audit review and brief meaning review. Those changes explain additional work
and lost overlap but do not prove that reasoning alone caused the slowdown.
This patch does not remove these checks, change model reasoning, or make new
paid requests speculatively.

## Reproduced local bottlenecks and fixes

1. Building source quantity options requested audit bindings 22 times. Each
   request revalidated the same accepted audit record and rebuilt the complete
   524-page discovery index. An instrumented trace attributed 34.4 seconds of
   39.3 seconds to those repeated accepted-record checks.
2. Planning with three saved takeaway-correction responses compiled four
   plans and ran plan validation 28 times. An instrumented trace ranked all
   document pages 36 times, including candidate retrieval for introductions
   without any legacy summary items to validate. The endpoint validator also
   built and searched the entire label catalog for prose with no endpoints.

The fix adds bounded, invocation-local reuse for deterministic quote
normalization, accepted-audit validation, and profile-page ranking. The audit
key includes the full document (text, layout, tables and navigation), profile,
observations and latest audit event. Ranking includes every page's text and
number, page count, nominated summary pages, ranking class and requested size.
Source changes invalidate reuse. Cached results are returned independently;
mutating a caller's list or binding cannot modify a cached approval.

The current target-subset check still runs outside the audit cache. A new
target cannot borrow an approval for the old target set, even when no source
data changed. A later unresolved audit event still blocks use. Caches are
bounded and cleared on return or exception; copied contexts cannot share them
between worker threads. No cache or source text is persisted by this change.

Empty legacy introductions no longer retrieve candidate sources. Missing
dynamic introduction audits still fail. Endpoint validation returns early
only when its existing endpoint pattern is absent, and retains the complete
clause list so possessive-ratio references still resolve against the preceding
clause. Numeric, evidence, semantic and export rules remain in force.

## Offline reproduction

Run from the repository root with development dependencies:

```powershell
python -m scripts.replay_validation_performance "path/to/analysis_data.json"
python -m scripts.replay_validation_performance "path/to/analysis_data.json" --profile
```

The script reconstructs excerpts from saved briefing evidence blocks and
restores original topic drafts before replaying the three recorded correction
responses. Optional visual suggestions are empty in both comparisons. It
blocks socket connections and fails if another model response is required.
It operates on copies, does not export a deck or approve the saved partial run,
and excludes initial JSON loading/deep-copy setup from the operation timings.
It prints output digests without printing document text.

The final comparison ran sequentially after regression tests finished. The
baseline loaded the prior deterministic validator bodies from HEAD `219dfb6`
in memory and disabled the new invocation cache; no checkout files changed.
Both runs used the same replay script, saved input and recorded responses.

| Local operation | Before | After |
| --- | ---: | ---: |
| Source quantity options | 23.578s | 3.527s |
| Planning replay | 35.962s | 22.024s |
| Combined measured work | 59.540s | 25.551s |

Source-option digest: `0efc1880831703d391dd67217a03c825bc2823ccc943e286872c6e6611d4057f`.
Plan digest: `ae275f6daf62c35024ca60fa6c17b1bfc7b2719c0a46adca13e0db8b50522c17`.
Each digest is identical before/after. The measured local work decreased by
33.989s (57%). Earlier measurements with different CPU contention were slower;
these are microbenchmarks, not a new end-to-end runtime or token-spending
estimate. Raw local logs are `tmp/perf-isolated-before.log` and
`tmp/perf-isolated-after.log`; they contain timings and hashes, not source text.

## Verification

Targeted tests exercise exact-input reuse, source/value/layout/check/page
changes, caller mutation, added targets, later failed audits, bounded memory,
thread isolation and exception cleanup. Existing introduction, scoped-value,
ratio, audit and deadline regressions are also run offline. The unrelated five
uncommitted summary files are preserved byte-for-byte. The 900-second deadline
and model request/retry policies are unchanged.

Full offline regression: **6,190 passed, 14 skipped**, with four pre-existing
Windows event-loop cleanup warnings in credential-isolation tests. Shards:
3,354 passed/5 skipped and 2,836 passed/9 skipped. Final cache, audit lifecycle
and export-entrypoint verification: **56 passed**. Earlier focused
introduction/endpoint tests: **124 passed**. Outbound connections were blocked
by the offline runner throughout; only loopback test transports were allowed.
Logs: `tmp/perf-full-0.log`, `tmp/perf-full-1.log`, and
`tmp/perf-final-targeted.log`.

No real model run, commit or push is part of this validation.
