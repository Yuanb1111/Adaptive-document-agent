# Bounded discovery overview (v45)

The reported failure occurred on call 27, `discovery / DiscoveryOverview`,
after routing, budget selection and 24 successful chunk discoveries. The
provider reported `finish_reason=length` with 8,192 output tokens and 20,582
input tokens. The overview request contained 80,152 characters. The failed
call's known cost estimate was CNY 0.05284824–0.10569648, part of the whole
run's CNY 0.15984524–0.31969048 estimate. These are the downloaded ledger's
public-price estimates, not provider billing. The failure preceded PPT export.

The old overview schema still allowed unlimited section/table/figure and
quality-note lists. Its prompt requested a full inventory even though chunk
discovery had already produced it. The ledger does not contain the failed
response body, so it cannot establish which field consumed those tokens.

The new synthesis prompt consumes every page-bound chunk summary and section
context. It omits repeated catalogs. Its schema bounds prose lengths, overview
points, supporting summary pages and new cross-section limitations, and rejects
extra fields. Python merges every exact chunk inventory entry and existing
quality note into the final profile, including sections, tables and figures.
Raw source objects and page evidence are unchanged. This applies to arbitrary
documents, with no issuer-specific rules.

The normal path uses one overview call. A truncated or schema-invalid overview
gets at most one shorter regeneration from the same source context. The failed
JSON is never supplied for completion or format repair. A second failure stops;
transport and privacy errors do not trigger this semantic recovery. Both
attempts remain in the usage ledger. Structured truncation errors now identify
the stage, operation, model and reported output tokens without exposing source
text.

A successful overview, including a recovered one, is cached under its source
context, prompt, schema and routing/privacy/generation settings. Failed outputs
are not cached. Chunk prompts, schemas and cache identities are unchanged.
Retries can reuse all completed chunks while their cache remains available;
a hosted restart may discard a session's temporary cache. The pipeline version
changes to `2026-09-28-bounded-discovery-overview-v45`, while extraction and
analysis cache versions remain unchanged.

Regression tests reproduce the 27th-call failure without a network request,
check the single-retry bound and complete evidence inventories, and verify
cached retries and truthful cost accounting. Offline tests cannot establish
the next real model run's wording, latency or monetary savings.

For the synthetic 24-chunk, 480-metric fixture, the source-summary context
shrinks from 16,619 to 2,343 characters (85.9%). This comparison excludes
system prompts and schemas and measures characters, not billed tokens. All
480 metrics still appear in the final profile.

Validation: the complete local suite passed with **1,248 passed, 3 skipped**
in 50.00 seconds. The skipped cases are Linux LibreOffice, opt-in local
rendering and Linux font integrations. No paid model request was made.
