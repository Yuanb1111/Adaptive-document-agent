"""Check explicit author-to-copy references without deciding semantic coverage."""
from pydantic import BaseModel, ConfigDict, Field

from adaptive_document_agent.services.source_quotes import normalize_quote


class AuthoredMeaningRef(BaseModel):
    model_config = ConfigDict(extra='forbid')
    part_id: str
    meaning_index: int = Field(ge=0)
    summary_quote: str = Field(min_length=1, max_length=6000)


def meaning_inventory(source):
    # Full owned quotations already remain in parts/source_quotes. The author
    # index identifies them without duplicating every passage in the prompt.
    return [dict(part_id=part['id'], meaning_index=index, meaning=value['meaning'])
            for part in source['parts'] for index, value in enumerate(part.get('required_meanings', []))]


def authored_coverage_errors(draft, source, catalog, audit):
    """Validate all exact references after layout/dedup; self-report never grants approval."""
    expected = {(row['part_id'], row['meaning_index']) for row in meaning_inventory(source)}
    if not expected:
        return []
    found, errors, records = set(), [], []
    for page_index, page in enumerate(draft.pages):
        for item_index, item in enumerate(page.items):
            item_id = f'g{page_index}_i{item_index}'
            owners = {catalog[fid][0].id for fid in item.fact_ids if fid in catalog}
            seen = set()
            for ref in item.meaning_refs:
                key = ref.part_id, ref.meaning_index
                quote = normalize_quote(ref.summary_quote)
                reference = key + (quote,)
                records.append(dict(item_id=item_id, **ref.model_dump(mode='json')))
                if key not in expected:
                    errors.append(f'Authored coverage references an unknown required meaning: {key}')
                elif ref.part_id not in owners:
                    errors.append(f'Authored coverage lacks its exact owning source binding: {key} at {item_id}')
                elif not quote or quote not in normalize_quote(item.text):
                    errors.append(f'Authored coverage quote is not visible in its exact paragraph: {key} at {item_id}')
                elif reference in seen:
                    errors.append(f'Authored coverage repeats an exact paragraph reference: {key} at {item_id}')
                else:
                    found.add(key)
                seen.add(reference)
    missing = sorted(expected - found)
    errors.extend(f'Authored coverage is missing required meaning: {part_id}[{index}]' for part_id, index in missing)
    audit['authored_meaning_coverage'] = dict(references=records,
        missing=[dict(part_id=part_id, meaning_index=index) for part_id, index in missing], errors=errors,
        expected_meaning_count=len(expected), structurally_complete=not errors,
        semantic_approval=False)
    return errors


def coverage_deficits(verdicts):
    """Stable failure identities come from model coverage judgments, not reason wording."""
    return {(v['part_id'], c['meaning_index']) for v in verdicts
            for c in v.get('coverage', []) if c.get('covered') is False}


def covered_meanings(verdicts):
    return {(v['part_id'], c['meaning_index']) for v in verdicts
            for c in v.get('coverage', []) if c.get('covered') is True}


def deficit_rows(keys):
    return [dict(part_id=part_id, meaning_index=index) for part_id, index in sorted(keys)]
