# v213: complete audit navigation within bounded requests

The `.935` v212 checkpoint failed before source discovery reached the model:
its serialized navigation contained 91 targets, 524 page entries, 20 complete
already-read pages and two source checks, totaling 279,198 characters against
the unchanged 260,000-character navigation limit.

Oversized navigation now has a second lossless serialization: one column header
and one row per page replace repeated page-index field names. Every preview,
physical page number, raw-value target hit and complete-reading size survives.
Optional reading-size fields remain optional; unknown fields fail instead of
disappearing. Targets, complete source text, source checks and identity maps are
unchanged. Requests that already fit retain their existing representation, and
requests that still exceed the limit fail before any model call. The `.935`
navigation becomes 221,924 characters with all original values retained.

The canonical local payload and full-source fingerprint are unchanged, so
source changes still invalidate saved navigation and audit approval. This is
transport compaction, not semantic selection, source truncation or assurance.

Real continuation also exposed an oversized supplementary-page selection. The
model's first correction shortened prose while retaining the same costly pages.
Source-discovery correction feedback now reports the deterministic full-page
cost of each added page, selection metadata cost, existing batch size and exact
excess. The model still chooses every replacement range. No source is pruned
automatically, and the 150,000-character evidence limit and one-correction
allowance remain unchanged. Complete pages must still pass independent audit.
After reduced-reasoning navigation continued to exceed the budget despite this
feedback, `AuditSourceDiscovery` now preserves provider-default reasoning. This
changes its request-policy/cache identity only; other selectors are unchanged.

The focused navigation/source-discovery suite passes 49 tests, including a
synthetic 91-target, 524-page case through the real LLMGateway with a mock client,
lossless Unicode/whitespace preservation, exact boundary admission, stale-source
detection, exact page-cost feedback and bounded rejection. Private checkpoints,
source data and real-provider diagnostic logs remain outside Git.

After the discovery reasoning policy change, 261 focused policy, routing and
editorial tests pass. The complete local Windows suite passes 6119 tests with
14 expected platform/opt-in/external-checkpoint skips. Four dependency event-loop
warnings remain. The sandboxed full run was interrupted after its thread dump
showed Streamlit's local socketpair blocked by the Windows sandbox; the successful
full run allowed loopback communication. Linux rendering remains a CI check.

Real validation against the original configured DeepSeek service passed source
selection under provider-default reasoning, then completed all 31 audit batches
covering all 91 targets. Every batch passed independent review; no dispositions
were supplied by the diagnostic driver. Earlier unsuccessful selections remain
in separate private attempt logs. This audit result alone is not export success.
