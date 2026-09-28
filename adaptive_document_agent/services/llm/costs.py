"""Versioned, offline price estimates; never presented as provider billing."""

from urllib.parse import urlparse

from .config import LLMSettings
from .usage import LLMUsage

PRICE_SOURCE = "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/"
PRICE_VERSION = "deepseek-cny-2026-09-28"
# CNY per million tokens, off-peak (cached input, uncached input, output).
DEEPSEEK_RATES = {
    "deepseek-flash": (0.02, 1.0, 4.0),
    "deepseek-v4-flash": (0.02, 1.0, 4.0),
    "deepseek-v4-flash-vision-exp": (0.02, 1.0, 4.0),
    "deepseek-v4-pro": (0.15, 4.5, 13.5),
}


def direct_deepseek(settings: LLMSettings, model: str) -> bool:
    """Do not apply direct-provider rates/policy to proxies or routed models."""
    endpoint = urlparse(settings.base_url or "https://api.deepseek.com")
    return (settings.provider.value == "deepseek" and endpoint.scheme == "https"
            and endpoint.hostname == "api.deepseek.com"
            and model.removeprefix("deepseek/") in DEEPSEEK_RATES)


def estimate_cost(usage: LLMUsage, settings: LLMSettings) -> None:
    """Annotate a new response, without retrospectively repricing old exports."""
    usage.estimated_cost = None
    usage.cost_currency = None
    if not direct_deepseek(settings, usage.model):
        usage.cost_details = {"status": "unknown", "reason": "No verified price card for this model/endpoint."}
        return
    rates = DEEPSEEK_RATES[usage.model.removeprefix("deepseek/")]
    details = {"status": "unknown", "price_version": PRICE_VERSION, "source": PRICE_SOURCE,
               "currency": "CNY", "price_band": settings.deepseek_price_band,
               "rates_off_peak_per_million": dict(zip(("cached_input", "uncached_input", "output"), rates)),
               "peak_multiplier": 2,
               "basis": "Public price snapshot, not a bill. Range covers both billing bands; explicit band is a user assumption."}
    usage.cost_currency = "CNY"
    usage.cost_details = details
    if usage.input_tokens is None or usage.output_tokens is None:
        details["reason"] = "Provider did not report complete input/output usage."
        return
    cached, missed = usage.cached_input_tokens, usage.uncached_input_tokens
    if cached is None and missed is not None:
        cached = usage.input_tokens - missed
    if missed is None and cached is not None:
        missed = usage.input_tokens - cached
    if cached is not None and (cached < 0 or missed < 0 or cached + missed != usage.input_tokens):
        details["reason"] = "Provider cache counts are inconsistent with input tokens."
        return
    low_factor = 2 if settings.deepseek_price_band == "peak" else 1
    high_factor = 1 if settings.deepseek_price_band == "off_peak" else 2
    cache_known = cached is not None
    low_counts = (cached, missed) if cache_known else (usage.input_tokens, 0)
    high_counts = (cached, missed) if cache_known else (0, usage.input_tokens)
    input_low = sum(a * b for a, b in zip(low_counts, rates)) * low_factor / 1_000_000
    input_high = sum(a * b for a, b in zip(high_counts, rates)) * high_factor / 1_000_000
    output_low = usage.output_tokens * rates[2] * low_factor / 1_000_000
    output_high = usage.output_tokens * rates[2] * high_factor / 1_000_000
    details.update(status="estimated" if cache_known and low_factor == high_factor else "range",
                   cache_split_known=cache_known,
                   input_cost_min=input_low, input_cost_max=input_high,
                   output_cost_min=output_low, output_cost_max=output_high,
                   estimated_cost_min=input_low + output_low,
                   estimated_cost_max=input_high + output_high)
    for name, count, rate in (("cached_input", cached, rates[0]), ("uncached_input", missed, rates[1])):
        for side, factor in (("min", low_factor), ("max", high_factor)):
            details[f"{name}_cost_{side}"] = count * rate * factor / 1_000_000 if count is not None else None
    if details["status"] == "estimated":
        usage.estimated_cost = input_low + output_low


def summarize_usage(records: list[dict]) -> dict:
    """Known subtotals + explicit coverage; missing calls never become zero cost."""
    groups = {}
    for record in records:
        stage = str(record.get("stage", "unknown"))
        currency = record.get("cost_currency") or (record.get("cost_details") or {}).get("currency") or "unknown"
        group = groups.setdefault((stage, currency), {
            "stage": stage, "currency": currency, "calls": 0, "app_cache_hits": 0,
            "priced_calls": 0, "unknown_cost_calls": 0, "unmetered_attempts": 0,
            "request_attempts": 0,
            "input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0, "uncached_input_tokens": 0,
            "reasoning_tokens": 0, "missing_token_calls": 0,
            "missing_cache_split_calls": 0, "missing_reasoning_calls": 0,
            "known_cost_min": 0.0, "known_cost_max": 0.0,
            "known_input_cost_min": 0.0, "known_input_cost_max": 0.0,
            "known_output_cost_min": 0.0, "known_output_cost_max": 0.0,
        })
        if record.get("cache_hit"):
            group["app_cache_hits"] += 1
            continue
        group["calls"] += 1
        group["request_attempts"] += max(1, len(record.get("attempts", [])))
        group["unmetered_attempts"] += sum(a.get("status") == "failed" for a in record.get("attempts", []))
        for name in ("input_tokens", "output_tokens", "cached_input_tokens", "uncached_input_tokens", "reasoning_tokens"):
            group[name] += record.get(name) or 0
        group["missing_token_calls"] += any(record.get(k) is None for k in ("input_tokens", "output_tokens"))
        group["missing_cache_split_calls"] += record.get("cached_input_tokens") is None
        group["missing_reasoning_calls"] += record.get("reasoning_tokens") is None
        details = record.get("cost_details") or {}
        if details.get("estimated_cost_min") is None or details.get("estimated_cost_max") is None:
            group["unknown_cost_calls"] += 1
        else:
            group["priced_calls"] += 1
            for side in ("min", "max"):
                group[f"known_cost_{side}"] += details[f"estimated_cost_{side}"]
                for kind in ("input", "output"):
                    group[f"known_{kind}_cost_{side}"] += details.get(f"{kind}_cost_{side}", 0)
    stages = list(groups.values())
    currencies = {}
    for row in stages:
        total = currencies.setdefault(row["currency"], {"currency": row["currency"]})
        for key, value in row.items():
            if key not in {"currency", "stage"}:
                total[key] = total.get(key, 0) + value
    for row in [*stages, *currencies.values()]:
        row["complete"] = row["unknown_cost_calls"] == 0 and row["unmetered_attempts"] == 0
        # A known subtotal is not a total when any requests/attempts are unmetered.
        row["estimated_total_min"] = row["known_cost_min"] if row["complete"] else None
        row["estimated_total_max"] = row["known_cost_max"] if row["complete"] else None
    return {"by_stage": stages, "by_currency": list(currencies.values()),
            "note": "Reasoning tokens are included in output, not added again. Unknown usage/cost is not zero. App cache hits make no model request. Failed retry billing is unknown."}
