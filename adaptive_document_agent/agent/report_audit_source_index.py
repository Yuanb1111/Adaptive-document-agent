"""Complete navigation metadata for model-selected assurance source reading."""
import json
from hashlib import sha256

from adaptive_document_agent.services.source_quotes import normalize_quote
from .source_coverage import inventory


MAX_DISCOVERY_INPUT_CHARS = 260_000


def digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def discovery_input(result, context):
    """Index every page; literal hits navigate only and never establish meaning."""
    physical_pages = [p.page_number for p in result.document.pages]
    if (len(physical_pages) != len(set(physical_pages))
            or set(physical_pages) != set(range(1, result.document.page_count+1))):
        raise ValueError('Complete physical-page navigation is unavailable; audit discovery cannot silently omit pages.')
    observations = context['observations']
    needles = [normalize_quote(o['raw_value']) for o in observations]
    page_index = []
    for page in result.document.pages:
        normalized = normalize_quote(page.text)
        # This is explicitly a navigation preview, never a quote or read page.
        heading = ' '.join(line.strip() for line in page.text.splitlines() if line.strip())[:140]
        page_index.append(dict(page=page.page_number, navigation_preview=heading,
            complete_text_chars=len(page.text),
            literal_raw_value_target_indices=[i for i, value in enumerate(needles)
                                              if value and value in normalized]))
    checks = result.profile.source_coverage.checks
    document_fingerprint = digest([
        dict(page=p.page_number, sha256=sha256(p.text.encode()).hexdigest()) for p in result.document.pages])
    payload = dict(document_source_fingerprint=document_fingerprint,
        targets=[dict(index=i, **{key: o.get(key) for key in (
            'id', 'metric_original', 'raw_value', 'value', 'period', 'entity', 'unit', 'raw_unit',
            'unit_scale', 'currency', 'fact_type', 'ifrs_status', 'unit_family')},
            evidence=o['evidence']) for i, o in enumerate(observations)],
        sections=[s.model_dump(mode='json') for s in inventory(result.document)],
        page_index=page_index,
        already_read_source_pages=context['source_pages'],
        source_checks=[{key: check.model_dump(mode='json')[key] for key in (
            'section_id', 'pages', 'status', 'reason', 'decision_impact', 'finding', 'evidence_quotes')}
            for check in checks],
        remaining_source_character_budget=150_000-len(json.dumps(context, ensure_ascii=False)),
        navigation_notice='Every physical page is indexed. Previews and literal value hits are navigation '
            'data only, not source quotations, metric matches, assurance or complete page reading.')
    if len(json.dumps(payload, ensure_ascii=False)) > MAX_DISCOVERY_INPUT_CHARS:
        raise ValueError('Complete audit source navigation exceeds its bounded input budget; no index entries were dropped.')
    # Page previews alone cannot keep a cached selection current after a source
    # body changes. Hash complete local text without sending unselected bodies.
    return payload, digest(payload)
