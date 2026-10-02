# PPT generation latency

The four changes reduce unnecessary model work without removing analysis,
source evidence, calculations, content validation, or rendered PowerPoint QA.

1. **Simple-operation reasoning.** Introduction-page selection, brief-page
   selection and format-only repair use reduced reasoning only when supported.
   Analytical decisions and substantive writing retain provider defaults. See
   [the exact capability and cache policy](LLM_REASONING_POLICY.md).
2. **Brief item patches.** Verified findings and citations are immutable. A single
   bounded patch can replace only rejected item positions, repair an invalid
   title, or add missing topic coverage within the existing item limit. The local
   merge passes the full evidence, duplicate, title and coverage gates. A rejected
   patch cannot rewrite verified items. Original drafts, patches and rejection
   details remain in the exported audit; any partial salvage emits a warning.
3. **Earlier introduction.** Concurrency-safe cloud clients start after discovery,
   from a copied document/profile snapshot, alongside independent analysis.
   Local, single-worker and stateful clients keep serial behavior. A gateway-wide
   admission bound limits all stages together. The caller alone attaches the
   introduction, rechecking the final source. Cancellation stops queued/subsequent
   work and drains unavoidable in-flight requests within their timeout/retry
   policy. Duration and final attachment wait are separate timing fields.
4. **Shared candidate rationale.** Repeated prose travels once in a typed list of
   rationale definitions. Each candidate keeps its own score, rejection decision,
   references and unique qualifications. Python expands the exact explanations
   before unchanged evidence weighting, ranking and selection. Conflicting IDs
   and missing references fail closed for affected candidates, with complete
   decisions/catalog entries retained in the score audit. The first returned
   score carries the response-wide audit. Legacy inline reasons remain supported.

## Reproduce the offline comparison

The runner accepts a worktree so the same current synthetic fixtures can exercise
both the original code and the optimized code in separate processes:

```bash
git worktree add --detach /tmp/ppt-latency-baseline 127fe124fcf0934117cb98eb6c9ee11c82896746
python -m scripts.benchmark_generation_latency --repo /tmp/ppt-latency-baseline --repeats 10 > baseline.json
python -m scripts.benchmark_generation_latency --repo . --repeats 10 > optimized.json
```

Run from this checkout with development dependencies installed. The introduction
harness uses real orchestration and gateway calls over synthetic source snapshots;
it replaces unrelated analysis work with disclosed fixed delays. The baseline
already overlaps introduction with slide planning. The comparison measures the
additional earlier overlap, not an artificially serial baseline. For tighter
paired measurement, alternate baseline/current process order between repetitions.

The reasoning, briefing and scoring cases disable application caching. Request
and response character counts include the schema and system prompt where labeled
as a full request. Provider token usage is unavailable, not zero; the optional
regex lexical-unit counts are not provider tokens. Every transport is a closed
synthetic stub with no real-provider fallback, credentials or paid requests.

## Deterministic fixture results

- Six-item briefing, one invalid item: the second response shrinks from 971 to
  166 characters (82.9%). Both versions use two calls and return the same six
  findings and citations. Full repair-request size changes from 8,092 to 8,173
  characters because the patch adds schema/instructions while retaining sources.
- Forty candidates: full request shrinks from 22,072 to 15,632 characters (29.2%);
  response shrinks from 31,352 to 17,647 (43.7%). Candidate payload alone shrinks
  from 20,662 to 12,834 (37.9%); that narrower count excludes the system prompt
  and response schema. Expanded scores, reasons, rejection decisions, ordering,
  selected analyses and observation references are identical.
- Scheduling: the comparison records per-stage durations, call intervals, wall
  time and output hashes. Ten alternating pairs measured 228.1 ms baseline versus
  128.3 ms optimized median (43.7% in this fixed-delay simulation only). Each run
  must contain exactly one introduction-page
  call and one introduction-draft call. Detailed paired results are recorded in
  `benchmarks/ppt-generation-latency-20261002.json`.

These measurements prove request-volume and scheduling changes on controlled
fixtures. They do **not** establish actual provider latency, reasoning-token
savings, natural model-output equivalence or a production speedup percentage.
A live comparison requires the same document, model configuration, controlled
cache state and authorized provider access. Summed concurrent request latencies
must not be presented as pipeline wall time. Rendering is a separate stage and
is not optimized by these changes.

The completed-result contract is v78. Extraction and discovery cache versions
are preserved; changed prompt/schema/reasoning identities invalidate the affected
model checkpoints. CI runs the full suite with real LibreOffice and adds the
current offline generation benchmark alongside the existing export benchmark.
