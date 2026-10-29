# V217: explicit consolidation of duplicate introduction meanings

The V216 `.436` diagnostic stopped after approximately 252 seconds in
`introduction_editorial`, before the retained-analysis reporting route. This
was a validation failure, not the 900-second deadline. An atomicity finding
identified a duplicate assertion in one source part. The writer claimed to
remove it, but the response schema supported only nonempty replacements.
Its second proposal echoed the same assertion. Both proposals correctly failed
the requirement that a claimed correction actually change the named target.

The resolution schema now supports explicit `merges`: the model names the exact
atomicity finding target and unchanged surviving meanings from the same source
part. Python checks addresses and ownership; it does not infer semantic
equivalence or interpret a prose deletion claim as an operation. A target with
another kind of defect cannot be merged. Cross-part references, duplicate
targets/keepers, merge chains, edited targets/keepers and incomplete finding
dispositions are rejected. At least one unchanged keeper must survive.

The full before/after inventories, original source passages, model proposals
and merge ledger remain available to the independent source reviewer. Historical
IDs explicitly use the before-resolution namespace because current IDs can
shift after consolidation. The reviewer must reject lost assertions, values,
conditions, periods, bases, attributions or qualifications. Structural success
does not grant semantic approval or allow publication after reviewer rejection.

This change adds no model operation or retry round. It extends the existing
resolution request and its one permitted protocol-feedback attempt. The V216
retained-analysis reporting strategy remains the default.

Regression coverage includes valid consolidation, malformed and unowned
deletion attempts, coexistence with another finding's real edit, bounded
feedback, historical/current identity mapping and complete introduction flows
with both independent acceptance and rejection. Private offline replay of
`.436` rejects the original responses and accepts a synthetic explicit merge
structurally (five meanings become four); it does not fabricate source-review
approval. The private diagnostic is not committed.

These offline checks do not establish DeepSeek cost, live model behavior or
end-to-end PPT completion time. The CNY 2–3 and 15-minute targets still require
a successful live run; no paid provider requests are made by these tests.
