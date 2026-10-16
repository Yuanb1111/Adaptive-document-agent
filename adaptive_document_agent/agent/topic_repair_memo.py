"""Invocation-owned reuse of explicitly rejected author requests, never approval."""
from collections import OrderedDict
from copy import deepcopy
from hashlib import sha256
import json

from adaptive_document_agent.services.llm import LLMGateway
from adaptive_document_agent.services.llm.config import LLMSettings


class RejectedTopicRepairMemo:
    """Keep bounded rejection diagnostics; source/settings exist only as digests."""

    def __init__(self):
        self._rejections = OrderedDict()

    def key(self, gateway, messages, schema, source_digest):
        # Custom/stateful gateway interfaces have no complete request identity.
        if type(gateway) is not LLMGateway or not isinstance(gateway.settings, LLMSettings):
            return None
        try:
            settings = gateway.settings
            credential = settings.api_key.get_secret_value() if settings.api_key else ''
            client_settings = getattr(gateway.client, 'settings', settings)
            if client_settings is not settings:
                return None
            value = dict(gateway=id(gateway), client=id(gateway.client),
                settings=settings.model_dump(mode='json', exclude={'api_key'}),
                credential_digest=sha256(credential.encode()).hexdigest(),
                capabilities=gateway.client.capabilities.model_dump(mode='json'),
                request_policy=gateway.client.request_policy(stage='presentation',
                    operation=schema.__name__, model=settings.model_for('presentation')),
                messages=messages, schema=schema.model_json_schema(), stage='presentation',
                allow_repair=False, max_tokens=None, source_digest=source_digest)
            return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()
        except (AttributeError, TypeError, ValueError):
            return None

    def get(self, key):
        if key is None or key not in self._rejections:
            return None
        self._rejections.move_to_end(key)
        return deepcopy(self._rejections[key])

    def reject(self, key, audit):
        if key is None:
            return
        self._rejections[key] = deepcopy(audit)
        self._rejections.move_to_end(key)
        while len(self._rejections) > 64:
            self._rejections.popitem(last=False)


def repair_source_digest(result, plan):
    """Include all source/selection/constraints; omit only execution diagnostics."""
    digest = sha256()
    for encoded in (result.model_dump_json(exclude={'validation_warnings', 'llm_usage',
            'presentation_export_trace', 'presentation_slide_counts'}), plan.model_dump_json()):
        value = encoded.encode()
        digest.update(len(value).to_bytes(8, 'big'))
        digest.update(value)
    return digest.hexdigest()
