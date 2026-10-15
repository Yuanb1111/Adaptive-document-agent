# Effective Luna effort and stable briefing inputs

The affected v138 run recorded reduced-reasoning intent but unsupported policy
status for lightweight operations on `gpt-6-luna`. In particular, a coverage
review spent its entire 8,192-token output budget on reasoning and returned no
usable output after about 91 seconds. Another avoidable cost was starting a
briefing before the presentation planner finished correcting topic wording;
changed topics correctly invalidated that briefing and caused regeneration.

## Scoped model capability

For the exact documented `gpt-6-luna` model on the official OpenAI endpoint,
lightweight operations can request supported low effort without depending on a
complete SDK price/capability catalog. The existing opt-out, routing, privacy,
cache policy identity and requested/applied parameter audit remain in force.
Unknown models, unverified aliases and custom/local endpoints do not inherit
this capability. Analytical topic selection, `BriefMeaningReview`,
`IntroductionAudienceReview` and `SummaryCoverageReview` retain their existing
reasoning defaults. Lightweight reviews already included in the reduced-effort
policy use low effort while retaining the same source and acceptance gates.
No provider or model is substituted.

The installed SDK's temperature rejection also mentions `reasoning_effort` in
its explanation. Compatibility handling now distinguishes the rejected clause
from its conditional explanation: a temperature-only rejection removes only
temperature and retains low effort. The existing single compatibility retry and
structured server-error checks are unchanged. Attempt and applied-policy audit
records verify that low effort survived the retry.

Official capability references:

- [GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna): low
  effort is supported; medium is the default.
- [API deployment checklist](https://developers.openai.com/api/docs/guides/deployment-checklist):
  lower effort is appropriate for focused extraction and routine transformations;
  changes require representative quality and latency evaluation.

## Start copy after topic corrections

For concurrent cloud runs with model-selected topics, the briefing starts only
after strict topic compilation and bounded takeaway corrections finish, while
optional visual planning can continue concurrently. Its isolated snapshot keeps
the verified company identity and source context. Serial/local/stateful clients
retain their existing request order. Existing final source, topic consistency,
numeric and independent semantic validation remain mandatory, and genuine late
input changes still cannot reuse stale copy. Invocation-owned resources retain
their cancellation, error propagation, audit and timing behavior.

This optimization does not shorten source reading, remove findings, skip review,
change page limits, introduce a settings toggle or weaken an export gate.
Offline tests verify parameter application and scheduling/request counts, not a
guaranteed wall-clock improvement. No real model requests or running-application
changes are required for that verification.

Verification: 225 reasoning/transport tests, 98 scheduling/planning lifecycle
tests and 426 adjacent gateway, briefing, introduction, pipeline and export
regressions passed (749 distinct tests). An additional offline check against the
installed SDK mapped the request to `reasoning_effort=low` with the unchanged
8,192-token completion cap; external connections were blocked and none were
attempted. Event-driven tests confirm corrected topics precede a single briefing
generation while visual planning overlaps, with company identity and page-level
evidence retained. No live-model latency or quality improvement is claimed by
these offline checks.
