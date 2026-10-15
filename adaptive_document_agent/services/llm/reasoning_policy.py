"""Bounded reasoning reductions, selected by operation rather than broad stage.

Unknown operations, model capabilities and custom endpoints retain provider defaults.
No prompts, credentials or content are used to decide this policy.
"""

import sys
from typing import Any
from urllib.parse import urlparse

from .config import LLMSettings, ProviderName
from .costs import direct_deepseek
from .credentials import DEFAULT_ENDPOINTS, provider_endpoint

REASONING_POLICY_VERSION = "operation-reasoning-v8"
# Documented model IDs, independent of pricing data. New aliases/models do not
# inherit transport capabilities by prefix. See docs/LLM_REASONING_POLICY.md.
_DEEPSEEK_THINKING_MODELS = frozenset({"deepseek-flash", "deepseek-v4-flash", "deepseek-v4-pro"})
# Official model documentation verified 2026-10-15: this exact model supports
# low effort and defaults to medium. It need not wait for LiteLLM's catalog to
# catch up. This declaration applies only after the official endpoint guard.
# https://developers.openai.com/api/docs/models/gpt-6-luna
_DOCUMENTED_OPENAI_LOW_EFFORT_MODELS = frozenset({"gpt-6-luna"})
_SIMPLE_OPERATIONS = frozenset({("presentation", "IntroductionPages"), ("report", "BriefSourcePages"),
                              ("presentation", "TopicCoverageReview"),
                              ("presentation", "TakeawayCorrection"),
                              ("report", "ExecutiveBriefPatch"),
                              # Editorial operations consume already validated analysis.
                              # Preserve deep reasoning in scoring, insights and topic selection.
                              ("report", "ExecutiveBrief"), ("report", "ReportPlan"),
                              ("presentation", "VisualSelection"),
                              ("presentation", "ReportRequirements"),
                              ("presentation", "SectionBindings"),
                              ("presentation", "CopyTranslations"),
                              ("presentation", "TranslationReview"),
                              ("presentation", "SummaryEditorialDraft"),
                              ("presentation", "SummaryReadBatch"),
                              ("presentation", "CompactSummaryDraft"),
                              ("presentation", "CompactSummaryReview"),
                              ("presentation", "SummaryStringRepairs"),
                              ("presentation", "SummarySynthesisRevision"),
                              ("presentation", "SummaryBodyAllocation"),
                              # Only a failed, split mapping assignment uses the
                              # configured reduced-reasoning recovery policy.
                              ("semantic", "SemanticResolutionRecovery"),
                              ("planner", "SemanticCandidateScores")})

# Bound structured responses without changing evidence or numerical validation.
_OUTPUT_LIMITS = {('planner', 'SemanticCandidateScores'): 12000,
                  ('semantic', 'SemanticResolution'): 12000,
                  ('semantic', 'SemanticResolutionRecovery'): 12000,
                  ('presentation', 'TakeawayCorrection'): 2000,
                  ('presentation', 'SummaryThemePlan'): 12000,
                  ('presentation', 'SummaryReadBatch'): 12000,
                  ('presentation', 'CompactSummaryDraft'): 8000,
                  ('presentation', 'CompactSummaryReview'): 8000,
                  ('presentation', 'SummaryStringRepairs'): 3000,
                  ('presentation', 'SummarySynthesisRevision'): 8000,
                  ('presentation', 'SummaryBodyAllocation'): 8000}


def reasoning_parameters(options: dict[str, Any]) -> dict[str, Any]:
    """Copy only the bounded, non-secret reasoning controls for audit records."""
    result = {}
    if options.get("reasoning_effort") is not None:
        result["reasoning_effort"] = options["reasoning_effort"]
    thinking = options.get("extra_body", {}).get("thinking")
    if isinstance(thinking, dict) and thinking.get("type") in {"enabled", "disabled"}:
        result["thinking"] = {"type": thinking["type"]}
    return result


def _supports_low_effort(settings: LLMSettings, model: str) -> bool:
    """Use an exact documented route or an already-loaded positive SDK entry.

    Generic/local servers cannot borrow capabilities from a same-named cloud model.
    Other missing or incomplete capability entries conservatively opt out.
    """
    provider = settings.provider
    if provider not in {ProviderName.OPENAI, ProviderName.GEMINI, ProviderName.OPENROUTER}:
        return False
    endpoint = urlparse(provider_endpoint(provider, settings.base_url) or "")
    official = urlparse(DEFAULT_ENDPOINTS[provider])
    if (endpoint.scheme, endpoint.netloc, endpoint.path.rstrip("/")) != (
            official.scheme, official.netloc, official.path.rstrip("/")) or endpoint.query or endpoint.fragment:
        return False
    route = provider.value
    model_id = model.removeprefix(route + "/")
    if provider == ProviderName.OPENAI and model_id in _DOCUMENTED_OPENAI_LOW_EFFORT_MODELS:
        # The source-verified declaration takes precedence over an absent or
        # stale SDK map, including its old negative/unknown capability flags.
        # Exact IDs only: no family, future snapshot, proxy or provider inference.
        return True
    try:
        # Even SDK capability helpers (or SDK initialization) can fetch catalogs
        # or consult ambient credentials. Never invoke them from policy lookup.
        # If LiteLLM is not loaded yet, preserve defaults for this request.
        litellm = sys.modules.get("litellm")
        catalog = vars(litellm).get("model_cost") if litellm is not None else None
        if not isinstance(catalog, dict):
            return False
        entry = catalog.get(f"{route}/{model_id}")
        if entry is None and provider == ProviderName.OPENAI:
            entry = catalog.get(model_id)
        if not isinstance(entry, dict) or entry.get("supports_reasoning") is not True:
            return False
        if entry.get("litellm_provider") != route:
            return False
        levels = entry.get("reasoning_effort_levels")
        if levels is not None and "low" not in levels:
            return False
        if entry.get("supports_low_reasoning_effort") is False:
            return False
        # A generic reasoning flag does not establish supported effort levels.
        # In particular, some pro/batch models accept only high/max. Fail closed
        # on older maps rather than infer support from a model-name substring.
        if entry.get("supports_low_reasoning_effort") is not True and (levels is None or "low" not in levels):
            return False
        # Never increase work on a model whose declared default is already low
        # or disabled, or unknown. Require affirmative evidence this is a
        # reduction. Omitting the option retains its configured/API default.
        if entry.get("default_reasoning_effort") not in {"medium", "high", "xhigh", "max"}:
            return False
        supported = entry.get("supported_openai_params")
        return isinstance(supported, (list, tuple, set, frozenset)) and "reasoning_effort" in supported
    except Exception:
        # Missing or malformed static metadata must not break a working configuration.
        return False


def _supports_deepseek_thinking(settings: LLMSettings, model: str) -> bool:
    """Verify both the exact model and official DeepSeek endpoint variant."""
    endpoint = urlparse(provider_endpoint(settings.provider, settings.base_url) or "")
    return (settings.provider == ProviderName.DEEPSEEK
            and model.removeprefix("deepseek/") in _DEEPSEEK_THINKING_MODELS
            and endpoint.scheme == "https" and endpoint.netloc == "api.deepseek.com"
            and endpoint.path.rstrip("/") in {"", "/v1", "/beta"}
            and not endpoint.query and not endpoint.fragment)


def request_reasoning_policy(settings: LLMSettings, *, stage: str | None,
                             operation: str, model: str) -> dict[str, Any]:
    """Return a serializable identity plus options for this exact request route."""
    simple = operation == "format_repair" or (stage, operation) in _SIMPLE_OPERATIONS
    intent = "reduce" if simple and settings.simple_task_reasoning == "reduced" else "preserve"
    options: dict[str, Any] = {}
    status = "provider_default"
    if simple:
        if intent == "reduce":
            if _supports_deepseek_thinking(settings, model):
                options = {"extra_body": {"thinking": {"type": "disabled"}}}
            elif _supports_low_effort(settings, model):
                options = {"reasoning_effort": "low"}
            status = "requested" if options else "unsupported"
    elif stage == "discovery" and settings.discovery_thinking != "provider_default":
        # Preserve the existing explicitly configured discovery policy. It is
        # independent of the new selector/repair policy and never affects synthesis.
        intent = settings.discovery_thinking
        if direct_deepseek(settings, model):
            options = {"extra_body": {"thinking": {"type": intent}}}
        status = "requested" if options else "unsupported"
    result = {"version": REASONING_POLICY_VERSION, "operation": operation,
            "intent": intent, "status": status, "requested": reasoning_parameters(options),
            "options": options}
    if (stage, operation) in _OUTPUT_LIMITS:
        result['output_token_limit'] = _OUTPUT_LIMITS[stage, operation]
    return result
