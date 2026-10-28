# Analysis spending deadline

Each analysis attempt has a shared monotonic deadline of 900 seconds. The UI
starts it when the attempt is created; direct orchestrator calls start it at
entry. Parallel workers and all format, capacity, compatibility and transport
retries share the deadline. A retry inside an attempt never resets it.

LLMGateway checks the deadline before admission and while waiting for a request
slot. The provider checks it again before each SDK call and caps the configured
request timeout at the remaining time. Expiration propagates as cancellation,
not as another semantic repair opportunity. No fallback provider is introduced.

Completed evidence, available validation diagnostics and all recorded usage are
retained in a partial result with `failed_stage=analysis_time_limit`. Reporting
can resume only when its stable extraction/calculation checkpoint exists. A
partial result cannot be published as a completed report. Polling does not
start another attempt; an explicit user retry starts a new 15-minute budget.

This bounds admission of paid work, not remote billing or process termination.
Already-submitted requests can still incur charges. SDK timeout handling,
local calculations, background draining and local PowerPoint export can take
additional time. Unknown usage from failed requests remains unknown, not zero.
Optional page-scope preview is a separate user action before the analysis timer.

## Failure .855

The exported run `analysis_data - 2026-10-28T161520.855.json` reports 110 calls,
2,364,437 input tokens (672,254 cached), and 411,575 output tokens, including
266,792 reported reasoning tokens. Reasoning is not added to output a second
time. Total input plus output: 2,776,012 tokens. The recorded price snapshot
estimates CNY 3.35192808–6.70385616; this is not a provider billing statement.
All calls have cost estimates. Wall time was 1,693.577 seconds.

The final executive-brief correction introduced `rmb 103.3 million`, which
failed source/quantity verification. The deadline limits future spending; it
does not change that semantic validation or guarantee successful export.

## Offline validation

Fake-clock tests exercise admission at the exact deadline, queued workers,
format repair, transport/compatibility retries, timeout propagation, late
successful usage, partial checkpoints and explicit-only UI retries. No real
model is called. Prior uncommitted briefing-prompt changes are separate.

Validation on 2026-10-28: full offline suite 6,175 passed, 14 skipped, with
four existing Windows event-loop cleanup warnings. After the final cleanup
boundary adjustment, 30 deadline/UI tests passed, including the additional
post-drain deadline case. The network-blocking runner allowed only loopback.
