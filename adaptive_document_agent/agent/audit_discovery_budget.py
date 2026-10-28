"""Deterministic page-cost feedback; only the model can revise source selection."""
import json

from .report_audit_context_budget import audit_context_budget, require_audit_context_budget


class AuditDiscoveryBudgetError(ValueError):
    def __init__(self, message, details):
        self.details = details
        super().__init__(message)


def require_discovery_budget(expanded, base):
    """Explain oversized full-page selections without dropping or trimming them."""
    try:
        return require_audit_context_budget(expanded)
    except ValueError as exc:
        current, proposed = audit_context_budget(base), audit_context_budget(expanded)
        existing = {p['page'] for p in base['source_pages']}
        added = [dict(page=p['page'], serialized_characters=len(json.dumps(
            p, ensure_ascii=False, separators=(',', ':'))) + 1)
            for p in expanded['source_pages'] if p['page'] not in existing]
        source_cost = sum(p['serialized_characters'] for p in added)
        details = dict(limit=current['limit'], base_batch_characters=current['largest_batch_characters'],
            remaining_characters=current['limit'] - current['largest_batch_characters'],
            selected_full_pages=added, added_page_characters=source_cost,
            selection_metadata_characters=proposed['largest_batch_characters']
                - current['largest_batch_characters'] - source_cost,
            proposed_batch_characters=proposed['largest_batch_characters'],
            excess_characters=proposed['largest_batch_characters'] - current['limit'],
            correction='Revise the selected page ranges to fit full-page costs plus selection metadata. '
                'Shortening reasons alone cannot remove page cost. Choose the most relevant complete '
                'source ranges; never truncate a page or required continuation, and never claim that '
                'unselected sources were read or that an unsupported target was verified. All targets '
                'remain assigned to independent review. Python has not selected replacement pages.')
        raise AuditDiscoveryBudgetError(str(exc), details) from exc
