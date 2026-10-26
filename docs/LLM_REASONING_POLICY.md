# Operation-level reasoning policy

The gateway distinguishes bounded retrieval/format and editorial operations from analysis,
without changing prompts, response validation, routing, credentials or privacy:

- `IntroductionPages` in `presentation` and `BriefSourcePages` in `report` reduce
  reasoning when the exact configured model and transport support it
- The single existing format-only repair attempt uses the same reduction policy
- `TopicCoverageReview` in `presentation` uses the same opt-out reduction. Its
  bounded output must contain explicit evidence decisions rather than spend
  the entire token allowance on internal reasoning. Full point context,
  source validation and the 24-batch, 36-call ceiling remain required; incomplete
  coverage remains unresolved and cannot certify business acceptance.
- `ExecutiveBriefPatch` uses the same reduction for its single targeted repair.
- `AuditSourceDiscovery` in `report` uses the configured reduction for source
  navigation. In v193, `AuditScopeDraft` and `AuditScopeReview` also honor the
  configured reduction. Building and independently checking assurance bindings still reconcile
  literal period/unit evidence, scope, table/column ownership and exact counterparts,
  including evidence against proposed unknown dispositions.
  Audit batches contain at most three exact target measures. Complete source
  pages, exact counterpart row/header/unit proofs, independent assurance review,
  Python value/period/unit/page checks and unknown dispositions remain required.
  The existing output limits and correction budgets do not change. Provider-default
  opt-out and exact route/capability checks still apply. The two assurance operations'
  identities change within policy v9; unrelated operation caches remain reusable.
  The existing strengthened unknown-review contract is unchanged. Approvals produced under it can be
  revalidated and reused independently of transport capacity failures.
- `TakeawayCorrection` uses the same opt-out reduction and a 2,000-token output
  bound. It rewrites only a withheld conclusion from its selected evidence;
  strict compilation must succeed before the conclusion is restored.
- `SummaryEditorialDraft`, `CompactSummaryDraft` and `CompactSummaryReview`
  use the same opt-out reduction. `SummaryReadBatch` now uses it for bounded
  structural reading and source-span capture. Complete line assignment, literal
  source ownership, numerical checks and independent compact-part meaning review
  remain required.
- In v147, initial owned-source synthesis, audience meaning
  selection/correction, final briefing meaning review, physical-budget review
  and incremental coverage decisions use the configured editorial reduction too.
  These operations still decide meaning through the model and retain their full
  independent source, quantity, qualification, coverage and physical-page gates.
  This avoids spending tens of thousands of reasoning tokens before emitting a
  bounded decision. Analytical discovery, resolution, insight generation and
  initial topic selection retain their existing policies. The explicit
  `provider_default` opt-out and exact route/capability checks remain effective.
  In v189, `IntroductionAudienceReview`, `SummaryLayoutPages` and
  `PhysicalBudgetSelection` also use the configured editorial reduction. The
  model still judges meaning, source qualifications and importance; current-draft
  binding, independent review, quantity/coverage validation and native physical
  measurements remain mandatory. Output capacity and repair budgets are unchanged.
  `provider_default` opts out. The existing exact model/endpoint guards apply.
  Their changed per-operation policy is part of each cache key; the common policy
  version remains v9 so unrelated extraction and analytical requests stay reusable.
- `SemanticCandidateScores` uses the opt-out reduction for bounded ranking of
  the supplied evidence-backed candidate set. Global context, explicit rationales,
  incomplete-decision quarantine and LLM semantic selection remain unchanged.
- `ExecutiveBrief` and `ReportPlan` in `report`, and `VisualSelection` in
  `presentation`, use reduced reasoning after the user chose lighter writing
  and layout on 2026-10-09. Complete numeric, unit, quote, source and qualification
  checks remain in place. Models, prompts and semantic selection stay unchanged.
- Semantic resolution, analytical topic selection, insight generation,
  `IntroductionDraft`, unknown operations and plain text generation keep defaults
- The existing `discovery_thinking` setting remains independent and unchanged

`LLM_SIMPLE_TASK_REASONING=reduced` is the default. Set `provider_default` to opt
out for selectors, repairs and editorial operations. A separate operation context preserves compatibility
with custom clients that implement only `request_context(stage=...)`; ContextVars
restore the original policy after errors, nested requests and concurrent requests.

## Capability and endpoint safety

For direct DeepSeek, verified IDs `deepseek-flash`, `deepseek-v4-flash` and
`deepseek-v4-pro` use `extra_body.thinking.type=disabled`. Optional `deepseek/`
transport prefixes retain the exact configured model. Accepted endpoint variants
are HTTPS `api.deepseek.com` at the root, `/v1` or `/beta`, without custom ports,
userinfo, queries or fragments. This capability list is independent of prices.
The configured alias `deepseek-flash` remains unchanged; this patch does not
substitute a model or guess which future version an alias resolves to.

For direct OpenAI, the exact documented model `gpt-6-luna` (optionally prefixed
`openai/` for transport) supports low effort and defaults to medium. The verified
declaration therefore requests `reasoning_effort=low` for the existing bounded
simple operations even when LiteLLM is not loaded or its model catalog is stale
or incomplete. The official declaration takes precedence over stale SDK flags;
it never grants capabilities to another model, future snapshot, provider or
custom endpoint. It is scoped to HTTPS `api.openai.com/v1` with no custom port,
userinfo, query or fragment. The existing opt-out, analytical operations,
independent meaning reviews, routing and strict validation remain unchanged.

Other OpenAI models, Gemini and OpenRouter use `reasoning_effort=low` only when the exact model's
already-loaded LiteLLM catalog entry positively declares low-effort support and
lists `reasoning_effort` in `supported_openai_params`. The catalog must also declare
a higher default (`medium`, `high`, `xhigh` or `max`). Disabled, minimal, low and
unknown defaults are preserved. Except for the verified exact Luna declaration,
missing/stale capabilities, unknown/new
model IDs, generic compatible endpoints, Ollama and local models receive no new
options. Policy lookup reads only static declared metadata: it does not initialize
LiteLLM or call SDK capability/model-info helpers, which can perform dynamic I/O.
If the SDK is not yet loaded, requests without the verified exact Luna declaration
conservatively keep defaults. There is no cloud fallback. Updating a model name
alone never grants capabilities beyond the independently verified declaration.
Incomplete LiteLLM catalogs may therefore leave other capable models unchanged.
The bounded runtime compatibility retry remains the safety net for a specifically
identified unsupported option; metadata alone is not a guarantee of acceptance.

Policy version, selected operation, routing, requested options and possible repair
policy are part of structured-cache identity. Each provider attempt records the
bounded reasoning options sent to LiteLLM. Usage records retain requested and
applied options and an explicit compatibility-downgrade status when a specifically
rejected option is removed for the single compatibility retry. “Applied” describes
the successful LiteLLM request, not an assertion about server-internal behavior;
provider-reported reasoning token counters remain the observed evidence.
For conditional LiteLLM compatibility errors, only the explicit rejection clause
identifies removable options. A temperature rejection's explanation can mention
`reasoning_effort` as advice; that does not remove an otherwise supported low
effort. The single compatibility retry and native structured-error checks remain
bounded and unchanged.

## Sources and verification

Reviewed 2026-10-02:

- [DeepSeek thinking controls](https://api-docs.deepseek.com/guides/thinking_mode/)
- [DeepSeek V4 model IDs](https://api-docs.deepseek.com/news/news260424/)
- [LiteLLM Gemini effort translation](https://docs.litellm.ai/docs/providers/gemini)
- [LiteLLM OpenRouter adapter](https://docs.litellm.ai/docs/providers/openrouter)
- [LiteLLM GPT-6.1 effort limits](https://docs.litellm.ai/blog/gpt_6_1_sol)

Verified for the exact Luna declaration on 2026-10-15:

- [GPT-6 Luna effort support and medium default](https://developers.openai.com/api/docs/models/gpt-6-luna)
- [OpenAI deployment checklist: low effort for bounded extraction and routine rewriting](https://developers.openai.com/api/docs/guides/deployment-checklist)

Regression tests use mocked provider responses and synthetic capabilities only.
They cover exact routing, safe opt-outs, both selector operations, preserved
complex operations, repair/context restoration, concurrency, cache invalidation,
compatibility downgrade auditing and local/credential isolation. No paid requests
or live generation latency/quality claims are part of this verification.

v111 also records bounded output budgets in the structured-cache policy identity:
candidate scoring 6,000 tokens, Summary reading 12,000, compact drafting/review
8,000 each. These apply through the provider adapter; an explicit caller token
limit takes precedence. Truncation remains an error with bounded recovery, never
permission to accept incomplete JSON or invent missing evidence.

v113 raises only candidate scoring's ceiling to 12,000 tokens. Its unchanged
40-candidate batches can now bisect down to single complete candidates, instead
of stopping after three splits with five candidates still present. The output
limit is already part of the gateway cache identity; other operation policies
and their cached successful responses retain their existing identities.
