"""Flat per-call cost ledger, retaining unknowns as empty cells."""

import csv
import io
import json


def usage_rows(records: list[dict]) -> list[dict]:
    fields = ("stage", "operation", "provider", "model", "resolved_model", "status", "cache_hit",
              "chunk_id", "source_page_start", "source_page_end", "parent_chunk_id",
              "fragment_index", "fragment_count", "recovery_depth",
              "started_at", "completed_at", "latency_ms", "thinking_mode", "finish_reason",
              "input_tokens", "cached_input_tokens", "uncached_input_tokens", "output_tokens",
              "reasoning_tokens", "total_tokens", "request_chars", "response_chars",
              "cost_currency", "estimated_cost")
    costs = ("price_version", "source", "price_band", "estimated_cost_min", "estimated_cost_max",
             "input_cost_min", "input_cost_max", "cached_input_cost_min", "cached_input_cost_max",
             "uncached_input_cost_min", "uncached_input_cost_max", "output_cost_min", "output_cost_max")
    return [{"call": index, **{key: row.get(key) for key in fields},
             **{key: (row.get("cost_details") or {}).get(key) for key in costs},
             "cost_status": (row.get("cost_details") or {}).get("status", "unknown"),
             "attempts": json.dumps(row.get("attempts", []), ensure_ascii=False)}
            for index, row in enumerate(records, 1)]


def export_usage_csv(records: list[dict]) -> bytes:
    rows = usage_rows(records)
    stream = io.StringIO(newline="")
    if rows:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            # Metadata can contain model/provider strings; never create Excel formulas.
            writer.writerow({key: "'" + value if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")) else value
                             for key, value in row.items()})
    return stream.getvalue().encode("utf-8-sig")
