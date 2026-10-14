"""Source and model identity for independently verified introduction themes."""
import json

from adaptive_document_agent.utils.hashing import sha256_bytes
from adaptive_document_agent.utils.pipeline_version import ANALYSIS_VERSION


def theme_cache_key(gateway, result, probe, title, opening):
    settings = gateway.settings
    payload = {'contract': ANALYSIS_VERSION, 'source': result.document.sha256,
        'title': title, 'opening': opening, 'parts': [p.model_dump(mode='json') for p in probe.parts],
        'provider': settings.provider.value, 'model': settings.model_for('presentation'),
        'endpoint': settings.base_url, 'privacy': settings.privacy_mode.value,
        'temperature': settings.temperature, 'purpose': result.profile.document_purpose,
        'requirements': (result.profile.report_requirements.model_dump(mode='json')
                         if result.profile.report_requirements else None),
        'policy': gateway.client.request_policy(stage='presentation', operation='CompactSummaryDraft',
                                                model=settings.model_for('presentation'))}
    return 'verified-summary-theme-' + sha256_bytes(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode())
