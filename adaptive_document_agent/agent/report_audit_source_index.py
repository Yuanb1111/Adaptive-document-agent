"""Complete navigation metadata for model-selected assurance source reading."""
import json
from hashlib import sha256

from adaptive_document_agent.services.source_quotes import normalize_quote
from .source_coverage import inventory


MAX_DISCOVERY_INPUT_CHARS = 260_000


def discovery_request(payload):
    """Bound the exact lossless wire payload, after replacing opaque addresses."""
    from .audit_discovery_references import reference_input
    wire, references = reference_input(payload)
    encoded = json.dumps(wire, ensure_ascii=False, separators=(',', ':'))
    if len(encoded) > MAX_DISCOVERY_INPUT_CHARS:
        raise ValueError('Complete audit source navigation exceeds its bounded input budget '
                         f'({len(encoded)} > {MAX_DISCOVERY_INPUT_CHARS} serialized characters); '
                         'no index entries were dropped.')
    return encoded, references


def digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def discovery_input(result, context):
    """Index every page; literal hits navigate only and never establish meaning."""
    from .report_audit_context_budget import audit_context_budget
    from .audit_source_layout import audit_source_page
    budget = audit_context_budget(context)
    physical_pages = [p.page_number for p in result.document.pages]
    if (len(physical_pages) != len(set(physical_pages))
            or set(physical_pages) != set(range(1, result.document.page_count+1))):
        raise ValueError('Complete physical-page navigation is unavailable; audit discovery cannot silently omit pages.')
    observations = context['observations']
    needles = [normalize_quote(o['raw_value']) for o in observations]
    page_index, source_fingerprints = [], []
    for page in result.document.pages:
        source = audit_source_page(page)
        source_fingerprints.append(dict(page=page.page_number, sha256=digest(source)))
        normalized = normalize_quote(page.text)
        # This is explicitly a navigation preview, never a quote or read page.
        heading = ' '.join(line.strip() for line in page.text.splitlines() if line.strip())[:140]
        page_index.append(dict(page=page.page_number, navigation_preview=heading,
            complete_text_chars=len(page.text),
            literal_raw_value_target_indices=[i for i, value in enumerate(needles)
                                              if value and value in normalized]))
        if 'layout_lines' in source:
            page_index[-1]['complete_reading_chars'] = len(json.dumps(source, ensure_ascii=False))
    checks = result.profile.source_coverage.checks
    document_fingerprint = digest(source_fingerprints)
    payload = dict(document_source_fingerprint=document_fingerprint,
        targets=[dict(index=i, **{key: o.get(key) for key in (
            'id', 'metric_original', 'raw_value', 'value', 'period', 'entity', 'unit', 'raw_unit',
            'unit_scale', 'currency', 'fact_type', 'ifrs_status', 'unit_family')},
            evidence=o['evidence']) for i, o in enumerate(observations)],
        sections=[s.model_dump(mode='json') for s in inventory(result.document)],
        page_index=page_index,
        # Navigation chooses pages, not column ownership. Complete text stays
        # here; coordinate evidence is supplied to the subsequent full review
        # and participates in its budget and source fingerprints.
        already_read_source_pages=[{key: page[key] for key in ('page', 'text')}
                                   for page in context['source_pages']],
        source_checks=[{key: check.model_dump(mode='json')[key] for key in (
            'section_id', 'pages', 'status', 'reason', 'decision_impact', 'finding', 'evidence_quotes')}
            for check in checks],
        remaining_source_character_budget=budget['limit']-budget['largest_batch_characters'],
        navigation_notice='Every physical page is indexed. Previews and literal value hits are navigation '
            'data only, not source quotations, metric matches, assurance or complete page reading.')
    # The canonical local ledger retains long source identities. Admission must
    # measure the identical serialized payload sent to the gateway, not that
    # larger ledger. JSON separator whitespace is not source content.
    discovery_request(payload)
    # Page previews alone cannot keep a cached selection current after a source
    # body changes. Hash complete local text without sending unselected bodies.
    return payload, digest(payload)
