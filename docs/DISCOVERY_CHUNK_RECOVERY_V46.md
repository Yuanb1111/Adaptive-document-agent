# Discovery chunk recovery and explicit retries (v46)

The new cost ledger contains 26 provider requests: routing, budget selection
and 24 chunk discoveries. Twenty-five requests succeeded; one `ChunkDiscovery`
returned `finish_reason=length` at 8,192 output tokens. That request had 11,293
input tokens and 48,879 request characters. No overview call was reached.
The known estimate for this run is CNY 0.121033–0.242066, including
CNY 0.03314772–0.06629544 for the failed request. These are public-price
estimates, not provider billing.

The earlier v45 fix handles `DiscoveryOverview` only. This failure occurs one
stage earlier and needs a separate recovery path. The old ledger does not
include source-page or chunk identifiers, so it cannot identify the failing
pages or explain why the application cache was unavailable. No source page
number or document identity is inferred from token counts.

Normal chunk requests retain their existing prompt, schema and cache identity.
On output truncation, recovery subdivides only the failed chunk. It uses
trusted source-page boundaries where available; an oversized single page uses
safe text boundaries while retaining its original page identity. Source text
is not sampled or shortened, and PDF text resembling page markers cannot
override trusted page numbers. Full successful child inventories are merged
by exact string identity, preserving distinct labels and conflicting records.

Recovery has a maximum depth of two and at most six child gateway calls per
failed parent. Existing provider transport/compatibility retries remain
separately recorded as request attempts. Children do not invoke a format-repair loop. The failed JSON is
never completed or used as evidence. If any required child cannot be recovered,
analysis fails instead of accepting a partial profile. Provider and privacy
settings stay unchanged; transport or privacy failures do not trigger splitting.

Successful children are cached independently. A recovery checkpoint allows a
later retry to resume the subdivision without buying the failed parent request
again. Only complete recovery creates a successful parent result. Cache bypass
continues to bypass both reads and writes. A deployment restart can still
discard temporary session caches.

Split checkpoints apply only to nodes that can still be subdivided. A failed
terminal fragment remains retryable after the user explicitly requests a new
attempt, while successful siblings remain cached. Complete recovered results
use the recovery prompt/schema/policy identity instead of masquerading as an
ordinary unsplit-model result.

The usage ledger and CSV now include chunk IDs, parent IDs, page ranges,
fragment indexes/counts and recovery depth. These are local diagnostics; they
do not enter provider API arguments, affect request cache identity or overwrite
token/cost fields. Structured truncation errors include the available page
range and chunk ID.

The UI remembers failure for the current document/settings scope. Ordinary
widget reruns show that failure without restarting paid analysis. The explicit
retry action reuses successful caches; changing the input/settings can still
start a fresh automatic analysis. Downloading the cost CSV no longer triggers
a page rerun. Failure and later-success ledgers remain separate runs, so total
spending across attempts requires both records.

The minimum Streamlit dependency is 1.43, which introduced the
[`download_button(on_click="ignore")` behavior](https://docs.streamlit.io/develop/quick-reference/release-notes/2025#version-1430).

The pipeline version is `2026-09-28-chunk-recovery-v46`. The extraction and
analysis cache versions remain unchanged. Regression tests use local synthetic
documents and mock models; they do not establish live-model cost or latency.

Validation: the complete local suite passed with **1,277 passed, 3 skipped**
in 104.51 seconds. The skipped cases are Linux LibreOffice, opt-in local
rendering and Linux font integrations. Regression coverage includes concurrent
chunk failure, Local Only, complete source preservation, explicit leaf retry,
recovery cache invalidation, UI rerun isolation and truthful per-call costs.
No paid model request was made.
