# Independent repairs for .774 and .381

These changes are separate from the earlier uncommitted briefing corrections.
No provider calls, commits or pushes are part of this validation.

## Audit navigation (.774)

The saved run exhausted 8,192 and 16,384 output tokens entirely on reasoning,
with zero response characters. Its 230,117-character navigation was within the
input limit. The failure preceded all audit batches and final briefing.

`AuditSourceDiscovery` now has its own 16,384 / 32,768 output limits. Both calls
retain identical complete input and provider-default reasoning. Only a proven
length truncation gets the larger request. Exhausting both saves an explicit
`output_capacity_exhausted` failure; it does not create an empty selection or
consume another format correction. The existing single selection correction
for a complete invalid response, source budgets, range/ID checks and independent
audit remain unchanged. This increases available capacity, not a guarantee that
every real model request will finish. Real-model validation remains pending.

## Native introduction layout (.381)

Network-disabled reproduction of the saved checkpoint isolated the extra page:
the original introduction rendered as five pages, but localized page four split
into two. Localization changed `US$` to `USD ` and added spaces after `RMB` in two
items. The old exact-string check replaced both authored `key_metrics` layouts
with plain paragraphs. All other introduction pages stayed at one slide.

The fix compares the entire ordered prose after the existing protected-money
spelling transform. Only that proven equivalence (including unchanged literal
coefficients, signs and non-money prose) can retain the authored layout. Exact
anchors are checked/remapped; stale anchors are removed. Changed meaning,
amounts, currencies, scales, dates and actual translations retain the conservative
paragraph fallback. This grants no semantic acceptance and does not change source
copy, reviewed localization, source parts or evidence bindings.

Introduction capacity checks now invoke the same native renderer and template
as export, caching only counts/copy-preservation results keyed by full copy,
structure, title and template revision. The renderer can use its existing plain
paragraph grid before splitting complete items. It never shrinks fonts or drops
copy. A native failure is an overflowing candidate, not permission to accept it.
Copy preservation uses the existing display normalization for authored newlines
and PowerPoint soft line breaks; words and spacing must still be preserved.

After localization, the orchestrator checks the actual composed deck again,
including introduction evidence coverage and all physical section budgets.
The diagnostic maps each logical introduction page to actual slide numbers.
An overflow remains `partial`, with reporting retry and
`failed_stage=final_presentation_layout`; completion is announced only after
the check. Native layout alternatives are lossless. This gate does not launch an
unbounded model rewrite or automatically discard source meanings.

The saved .381 checkpoint now passes native composition, export preflight,
geometry, source/summary binding, language and physical-budget checks and creates
an editable PPTX: 18 total slides, 17 body slides, 5 introduction slides and 7
analysis slides. Its document, observations, calculations, introduction copy,
localized strings and original checkpoint remain unchanged. This is an offline
export of existing reviewed content, not a new extraction or model validation.

Private reproduction scripts, diagnostic JSON, PPTX files and regression logs
are kept under ignored `tmp/`. The prior five uncommitted briefing files are
tracked by SHA-256 in a private manifest and must remain byte-for-byte unchanged.

The saved .774 navigation also passed an offline failure-injection replay with
20 targets and the original 230,117-character input: both output allowances were
exercised with identical requests, no audit batch started after exhaustion, and
the explicit capacity diagnostic was retained. These were scripted responses,
not a real-provider completion or semantic audit approval.

## Final offline regression

All test files ran in two disjoint shards with external socket connections
blocked and loopback permitted for local test servers. The final results were
3,284 passed / 5 skipped and 2,870 passed / 9 skipped: **6,154 passed, 14 skipped,
zero failures**. Four warnings came from LiteLLM event-loop deprecation and
Windows asyncio event-loop cleanup in provider credential-isolation tests.
No real model calls were made. Native PPTX structure and export checks passed;
this validation does not claim rasterized visual review or real-model success.

The earlier five uncommitted files remained byte-identical. No commit or push
was performed; HEAD remained `afbc45b562bfefea310017dbc45cb18f1c259626`.
