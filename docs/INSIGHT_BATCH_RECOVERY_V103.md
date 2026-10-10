# Insight output truncation recovery (v103)

A run can stop at 75% with `InsightList` and `finish_reason=length`, even after
the calculation and extraction stages have succeeded. This is an incomplete
model response, not evidence that the PDF or customization request is invalid.
Reasoning tokens may consume part of the model's output allowance; the displayed
total alone does not establish how much usable JSON was generated.

Previously the insight generator submitted every validated calculation in one
request. It now packs complete results into requests with at most six results
and a target of 32,000 JSON characters. A calculation, its linked observations,
and the exact supplied source context remain together. An indivisible result
larger than the target is sent alone; it is never sliced or sampled to meet the
target. Source retrieval retains its existing shared excerpt budget.

The prompt asks for concise findings, at most one per result, and empty output
evidence lists. Python binds evidence from the validated results and separately
checks any driver's literal quote and source page. A draft cannot link a result
outside its supplied batch, even if that result exists elsewhere in the run.
Report and presentation planning still receive the combined accepted findings.

Only a structured response with `finish_reason=length` triggers batch bisection.
Every child receives complete records and the same source excerpts. Partial
JSON is discarded, including syntactically valid JSON labelled truncated by the
provider. A singleton failure stops with its task ID instead of repeating the
same call, silently dropping evidence, or switching providers. Transport and
privacy failures propagate normally. Ordinary format errors retain the gateway's
existing one-repair limit. A batch of n results makes at most 2n-1 generation
requests if every result requires splitting; singleton failures stop recovery.

All requests pass through `LLMGateway`, retain the selected insight model and
reasoning policy, and record usage for failed parents and successful children.
Successful batch responses remain independently cached. Retrying a previously
split request may still call its uncached failed parent, but successful sibling
and child responses reuse their exact cache entries. The analysis cache version
remains unchanged because extraction, calculations, and earlier model contracts
are unchanged; updated insight instructions invalidate the insight requests.

After deploying v103, keep the original PDF, customization and model settings,
then use **Retry analysis (reuse successful cache)**. Cached successful earlier
requests can be reused when their request identity and session cache remain
available. A deployment restart or session change can limit that reuse.

Offline regressions simulate the screenshot's 65,536-token truncation, verify
complete result/evidence preservation, retry caching, model routing, untrusted
content boundaries, singleton exhaustion, cross-batch citation rejection, and
transport/privacy failure behavior. They do not prove a particular live model
run will succeed; a singleton can still exhaust that model's output allowance.
