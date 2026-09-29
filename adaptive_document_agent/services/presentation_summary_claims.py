"""Validate each summary claim against its own bound, visibly supported facts."""

from adaptive_document_agent.models import PresentationVisualBlock
from adaptive_document_agent.validation.narrative_plan_validator import expanded_observation_ids
from .presentation_share_claims import share_claims, share_direction_supported


def prepare_summary_claims(plan, eligible, by_id, charts, totals, definitions=()):
    from .presentation_claim_evidence import _RANK, _SHARE, _reported_shares, _ranking_peers, visible_observation_ids
    from .presentation_ratio_definitions import source_defined_possessive_share
    from .presentation_share_claims import source_row

    analyses = [slide for slide in plan.slides if slide.slide_type == "analysis"]
    notes = []
    for summary in [slide for slide in plan.slides if slide.slide_type == "executive_summary"]:
        for index, text in enumerate(summary.bullets):
            if not (_SHARE.search(text) or _RANK.search(text)):
                continue
            ids = summary.bullet_observation_ids[index] if index < len(summary.bullet_observation_ids) else []
            exact = [slide for slide in analyses if text in {slide.title, slide.message}]
            if not ids and len(exact) == 1:
                ids = expanded_observation_ids(exact[0], charts)
            selected = [by_id[oid] for oid in ids if oid in by_id]
            themes = [theme for theme in plan.themes if theme.observation_ids
                      and set(theme.observation_ids) <= set(ids)]
            owners = exact or [slide for slide in analyses if len(themes) == 1 and slide.theme_id == themes[0].id]
            owner = owners[0] if len(owners) == 1 else None
            displayed = [by_id[oid] for oid in visible_observation_ids(owner, charts)
                         if oid in by_id and oid in ids] if owner else []
            qualifications = [note for theme in themes for note in theme.caveats]
            claims = share_claims(selected, text)
            supported, evidence = claims is not None and bool(selected), []
            if claims is None:
                sourced = source_defined_possessive_share(text, selected, displayed, eligible, definitions)
                if sourced:
                    supported = True
                    evidence.extend(sourced)
            for claim in claims or []:
                scoped = displayed if any(source_row(item) == claim.subject for item in displayed) else selected
                bound = _reported_shares(scoped, eligible, claim.text, subject=claim.subject,
                                         denominator=claim.denominator, totals=totals)
                if not bound or not share_direction_supported(bound, claim.text, qualifications):
                    supported = False
                    break
                evidence.extend(bound)
            if _RANK.search(text):
                bound = _reported_shares(displayed or selected, eligible, text, ranking=True)
                peers = _ranking_peers(bound, eligible, text) if bound else []
                supported = supported and bool(peers)
                evidence.extend(peers)
            evidence = list({item.id: item for item in evidence}.values())
            visible = {oid for slide in analyses for cid in [*slide.chart_ids,
                       *(cid for block in slide.visual_blocks for cid in block.chart_ids)]
                       if cid in charts for oid in charts[cid].observation_ids}
            visible.update(oid for slide in analyses for block in slide.visual_blocks
                           if block.role in {"table", "kpi"} for oid in block.observation_ids)
            missing = [item.id for item in evidence if item.id not in visible]
            if supported and missing:
                if (owner is None or len(owner.visual_blocks) >= 4 or len(missing) > 12
                        or len(set(owner.observation_ids) | set(missing)) > 40):
                    supported = False
                else:
                    owner.visual_blocks.insert(0, PresentationVisualBlock(role="table", observation_ids=missing))
                    owner.observation_ids = list(dict.fromkeys([*owner.observation_ids, *missing]))
                    owner.source_pages = sorted(set(owner.source_pages) | {e.page for item in evidence for e in item.evidence})
                    theme = next((theme for theme in plan.themes if theme.id == owner.theme_id), None)
                    if theme:
                        theme.observation_ids = list(dict.fromkeys([*theme.observation_ids, *missing]))
                        theme.source_pages = sorted(set(theme.source_pages) | set(owner.source_pages))
                    notes.append(f"Slide {owner.id}: added source-bound share evidence for summary item {index + 1}")
            if not supported:
                candidates = [theme.title for theme in themes] + [slide.section_title for slide in owners]
                summary.bullets[index] = next((value for value in candidates if value.strip()
                    and not (_SHARE.search(value) or _RANK.search(value))), "Reported measures")
                notes.append(f"Slide {summary.id}: narrowed comparative summary item {index + 1} without compatible visible shares")
    return notes
