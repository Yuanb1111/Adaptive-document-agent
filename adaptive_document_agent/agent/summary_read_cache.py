"""Reuse only source-bound reading batches that pass current evidence checks."""
import json

from pydantic import BaseModel

from adaptive_document_agent.models.summary import SummaryPart, SummaryReview
from adaptive_document_agent.services.summary_validation import reading_errors
from adaptive_document_agent.utils.hashing import sha256_bytes
from adaptive_document_agent.utils.pipeline_version import ANALYSIS_VERSION


class ValidatedReadingBatch(BaseModel):
    parts: list[SummaryPart]
    audit: dict


def reading_cache_key(gateway, result, blocks, rules):
    if not getattr(gateway, 'cache_enabled', False) or not getattr(gateway, 'cache', None):
        return None
    settings = gateway.settings
    payload = {'version': ANALYSIS_VERSION, 'rules': rules,
        'document_id': result.document.document_id, 'sha256': result.document.sha256,
        'blocks': [b.model_dump(mode='json') for b in blocks],
        'provider': settings.provider.value, 'model': settings.model_for('presentation'),
        'endpoint': settings.base_url, 'privacy': settings.privacy_mode.value,
        'temperature': settings.temperature,
        'policy': gateway.client.request_policy(stage='presentation', operation='SummaryReadBatch',
                                               model=settings.model_for('presentation'))}
    return 'verified-summary-reading-' + sha256_bytes(json.dumps(payload, sort_keys=True,
                                                                ensure_ascii=False).encode())


def cached_reading(gateway, key, result, blocks):
    if key is None:
        return None
    cached = gateway.cache.get_model(key, ValidatedReadingBatch)
    if cached is None:
        return None
    probe = SummaryReview(document_id=result.document.document_id,
        document_sha256=result.document.sha256, source_pages=sorted({b.page for b in blocks}),
        source_blocks=blocks, parts=cached.parts)
    if reading_errors(probe, result, complete_scope=False):
        gateway.cache.remove_model(key)
        return None
    gateway.record_cache_hit(stage='presentation', operation='SummaryReadBatch', request_metadata={
        'source_page_start': min(b.page for b in blocks), 'source_page_end': max(b.page for b in blocks)})
    cached.audit.update(validated_batch_cache=True,
                        reused_duration_ms=cached.audit.get('duration_ms', 0), duration_ms=0)
    return cached
