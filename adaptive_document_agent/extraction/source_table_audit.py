"""Separate source-layout completeness from unchanged export-cell transport."""
from hashlib import sha256
import json


def table_digest(table):
    fields=('page','bbox','reading_bbox','source_rotation','raw_header_cells',
            'raw_header_spans','raw_header_lines','raw_cells','raw_body_lines',
            'raw_context_lines','raw_footnotes')
    return sha256(json.dumps({name:getattr(table,name) for name in fields},
                            sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def page_inventory_errors(page):
    audit=page.source_table_inventory
    if audit.get('status')!='checked' or audit.get('method')!='independent_decoded_ruling_geometry':
        return ['Independent source-layout inventory is unavailable']
    if audit.get('unresolved_regions'):
        return ['Source table regions remain unresolved']
    tables=page.raw_tables
    if set(audit.get('table_ids',[]))!={t.table_id for t in tables} or audit.get('region_count')!=len(tables):
        return ['Source-layout regions do not match the retained original tables']
    errors=[]
    for table in tables:
        if audit.get('table_digests',{}).get(table.table_id)!=table_digest(table):
            errors.append('Original table layout or annotations changed: '+table.table_id)
        if not table.raw_header_cells:
            errors.append('Original table has no resolved literal headers: '+table.table_id)
        if any('\ufffd' in str(cell) or '(cid:' in str(cell)
               for row in [*table.raw_header_cells,*table.raw_cells] for cell in row):
            errors.append('Original table retains undecoded characters: '+table.table_id)
    return errors
