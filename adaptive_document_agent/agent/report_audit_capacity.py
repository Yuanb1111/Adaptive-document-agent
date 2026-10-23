"""Capacity failures are transport-specific; completed source approvals are not."""
from hashlib import sha256
import json

from adaptive_document_agent.services.llm.credentials import provider_endpoint


# Start at the previously successful recovery capacity. Reasoning shares this
# allowance with JSON; too-small first requests discard all completed reasoning
# and repeat the same evidence. Keep one bounded length-only recovery, without
# changing model, reasoning policy, evidence or independent acceptance gates.
AUDIT_DRAFT_TOKEN_LIMITS = (20000, 32000)
AUDIT_REVIEW_TOKEN_LIMITS = (16384, 24000)
CAPACITY_CONTRACT = 'audit-capacity-route-policy-review-contract-v174'


def audit_capacity_identity(gateway, request_strategy):
    """Hash the exact configured wire policy without storing custom URLs or keys.

    Unknown custom gateways can run the same bounded review, but cannot reuse
    prior capacity failures without an identifiable route and request policy.
    This reads the same local policy metadata as LLMGateway; no provider I/O.
    """
    settings, client = getattr(gateway, 'settings', None), getattr(gateway, 'client', None)
    if (settings is None or client is None or not callable(getattr(settings, 'model_for', None))
            or not callable(getattr(client, 'request_policy', None))):
        return None
    model = settings.model_for('report')
    operations = {}
    for operation, limits in [('AuditScopeDraft', AUDIT_DRAFT_TOKEN_LIMITS),
                              ('AuditScopeReview', AUDIT_REVIEW_TOKEN_LIMITS)]:
        policy = client.request_policy(stage='report', operation=operation, model=model)
        if not isinstance(policy, dict):
            return None
        operations[operation] = dict(request_policy=policy, token_limits=limits)
    identity = dict(contract=CAPACITY_CONTRACT, request_strategy=request_strategy,
        provider=settings.provider.value, endpoint=provider_endpoint(settings.provider, settings.base_url),
        model=model, privacy=settings.privacy_mode.value, temperature=settings.temperature,
        operations=operations)
    return dict(contract=CAPACITY_CONTRACT, fingerprint=sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode()).hexdigest())
