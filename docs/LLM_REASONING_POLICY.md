# Operation-level reasoning policy

The gateway distinguishes bounded retrieval/format operations from synthesis,
without changing prompts, response validation, routing, credentials or privacy:

- `IntroductionPages` in `presentation` and `BriefSourcePages` in `report` reduce
  reasoning when the exact configured model and transport support it
- The single existing format-only repair attempt uses the same reduction policy
- `TopicCoverageReview` in `presentation` uses the same opt-out reduction. Its
  bounded output must contain explicit evidence decisions rather than spend
  the entire token allowance on internal reasoning. Full point context,
  source validation and the three-call budget remain required; incomplete
  coverage remains unresolved and cannot certify business acceptance.
- Semantic resolution, planning, insight generation, `ExecutiveBrief`,
  `IntroductionDraft`, unknown operations and plain text generation keep defaults
- The existing `discovery_thinking` setting remains independent and unchanged

`LLM_SIMPLE_TASK_REASONING=reduced` is the default. Set `provider_default` to opt
out for selectors and repairs. A separate operation context preserves compatibility
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

OpenAI, Gemini and OpenRouter use `reasoning_effort=low` only when the exact model's
already-loaded LiteLLM catalog entry positively declares low-effort support and
lists `reasoning_effort` in `supported_openai_params`. The catalog must also declare
a higher default (`medium`, `high`, `xhigh` or `max`). Disabled, minimal, low and
unknown defaults are preserved. Missing/stale capabilities, unknown/new
model IDs, generic compatible endpoints, Ollama and local models receive no new
options. Policy lookup reads only static declared metadata: it does not initialize
LiteLLM or call SDK capability/model-info helpers, which can perform dynamic I/O.
If the SDK is not yet loaded, this request conservatively keeps defaults. There is
no cloud fallback. Updating a model name alone never grants new capabilities.
Incomplete LiteLLM catalogs may therefore leave otherwise capable models unchanged.
The bounded runtime compatibility retry remains the safety net for a specifically
identified unsupported option; metadata alone is not a guarantee of acceptance.

Policy version, selected operation, routing, requested options and possible repair
policy are part of structured-cache identity. Each provider attempt records the
bounded reasoning options sent to LiteLLM. Usage records retain requested and
applied options and an explicit compatibility-downgrade status when a specifically
rejected option is removed for the single compatibility retry. “Applied” describes
the successful LiteLLM request, not an assertion about server-internal behavior;
provider-reported reasoning token counters remain the observed evidence.

## Sources and verification

Reviewed 2026-10-02:

- [DeepSeek thinking controls](https://api-docs.deepseek.com/guides/thinking_mode/)
- [DeepSeek V4 model IDs](https://api-docs.deepseek.com/news/news260424/)
- [LiteLLM Gemini effort translation](https://docs.litellm.ai/docs/providers/gemini)
- [LiteLLM OpenRouter adapter](https://docs.litellm.ai/docs/providers/openrouter)
- [LiteLLM GPT-6.1 effort limits](https://docs.litellm.ai/blog/gpt_6_1_sol)

Regression tests use mocked provider responses and synthetic capabilities only.
They cover exact routing, safe opt-outs, both selector operations, preserved
complex operations, repair/context restoration, concurrency, cache invalidation,
compatibility downgrade auditing and local/credential isolation. No paid requests
or live generation latency/quality claims are part of this verification.
