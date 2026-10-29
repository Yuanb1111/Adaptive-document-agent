"""Address checks for model-proposed same-part redundancy consolidation.

Python never decides semantic equivalence. A proposal can remove only an exact
atomicity finding target and must name unchanged, surviving meanings in its own
source part. The independent full-source reviewer decides preservation.
"""
from pydantic import BaseModel, ConfigDict, Field


class MeaningResolutionMerge(BaseModel):
    model_config = ConfigDict(extra='forbid')
    meaning_id: str = Field(description='Exact BEFORE-RESOLUTION atomicity finding target to consolidate')
    retained_meaning_ids: list[str] = Field(min_length=1, description=
        'Distinct unchanged surviving BEFORE-RESOLUTION meanings in the SAME source part '
        'that together preserve every assertion, condition, attribution and qualification of the target')
    reason: str = Field(min_length=1, max_length=2000)


MERGE_INSTRUCTIONS = (
    'For a redundant meaning identified by an atomicity finding, use merges rather than '
    'claiming deletion in prose or echoing unchanged text in edits. Set meaning_id to the '
    'exact finding target, retained_meaning_ids to distinct UNCHANGED surviving meanings '
    'from its SAME source part, and explain complete semantic preservation. Only those '
    'named targets are removed; keepers remain unchanged. Do not merge across parts, '
    'chain merges, edit a merge target/keeper, or remove a unique condition, number, '
    'period, basis or attribution. A mixed/unsupported assertion needs a real edit, not '
    'deletion disguised as redundancy. Each target finding disposition must be '
    'classification=atomicity, action=corrected, and reference exactly the target plus '
    'its keepers in the BEFORE-RESOLUTION namespace. If no eligible keeper fully preserves '
    'the target, do not merge. Neither a merge reason nor structural validation is approval; '
    'the complete revised union still requires fresh independent source review. ')


def validate_merges(response, meanings, findings, resolutions, changed, edited_ids):
    merges = {m.meaning_id: m for m in response.merges}
    if len(merges) != len(response.merges):
        raise ValueError('Meaning merges must identify each target once')
    targets = set(merges)
    for target, merge in merges.items():
        owned_findings = [f for f in findings.values() if f.get('meaning_id') == target]
        if (target not in meanings or not owned_findings or target in edited_ids
                or any(f['kind'] != 'meaning' or f.get('issue_type') != 'atomicity' for f in owned_findings)):
            raise ValueError('Meaning merge requires an unedited exact atomicity finding target')
        keepers = merge.retained_meaning_ids
        if (not merge.reason.strip() or not keepers or len(keepers) != len(set(keepers))
                or any(k not in meanings or k in targets or k in changed or k in edited_ids
                       or meanings[k]['part_id'] != meanings[target]['part_id'] for k in keepers)):
            raise ValueError('Meaning merge requires unchanged surviving references from the same source part')
        for finding in owned_findings:
            entry = resolutions[finding['finding_id']]
            refs = entry.referenced_meaning_ids
            if (entry.action != 'corrected' or entry.classification != 'atomicity'
                    or len(refs) != len(set(refs)) or set(refs) != {target, *keepers}):
                raise ValueError('Meaning merge disposition must reference its exact target and all surviving keepers')
    return targets
