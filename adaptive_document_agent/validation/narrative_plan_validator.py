"""Validate thematic evidence boundaries without substituting Python for semantics."""

from adaptive_document_agent.services.presentation_evidence import calculation_catalog


def expanded_observation_ids(owner, charts) -> set[str]:
    ids = set(owner.observation_ids)
    cids = set(owner.chart_ids)
    for block in getattr(owner, "visual_blocks", []):
        ids.update(block.observation_ids)
        cids.update(block.chart_ids)
    for cid in cids:
        if cid in charts:
            ids.update(charts[cid].observation_ids)
            ids.update(charts[cid].total_observation_ids)
    return ids


def validate_narrative_plan(plan, result, calculations=None) -> list[str]:
    from .presentation_plan_validator import PresentationPlanValidator

    errors = []
    observations = {o.id: o for o in result.observations}
    charts = {c.id: c for c in result.charts}
    insights = {i.id: i for i in result.insights}
    calculations = calculations if calculations is not None else calculation_catalog(result.observations)
    themes = {t.id: t for t in plan.themes}
    if len(themes) != len(plan.themes):
        errors.append("theme IDs must be unique")
    signatures = set()
    for theme in plan.themes:
        if not all(s.strip() for s in (theme.id, theme.title, theme.question, theme.rationale)):
            errors.append(f"theme {theme.id} needs a title, analytical question and selection rationale")
        if set(theme.chart_ids) - charts.keys() or set(theme.observation_ids) - observations.keys() or set(theme.insight_ids) - insights.keys():
            errors.append(f"theme {theme.id} references unknown evidence")
        ids = expanded_observation_ids(theme, charts)
        if not ids and not theme.insight_ids:
            errors.append(f"theme {theme.id} has no retained evidence")
        pages = {e.page for oid in ids if oid in observations for e in observations[oid].evidence}
        pages.update(e.page for iid in theme.insight_ids if iid in insights for e in insights[iid].evidence)
        if set(theme.source_pages) != pages:
            errors.append(f"theme {theme.id} source pages must match its retained evidence")
        if any(not observations[oid].evidence or observations[oid].validation_status not in {"valid", "partially_valid"}
               for oid in ids if oid in observations):
            errors.append(f"theme {theme.id} includes invalid or ungrounded observations")
        allowed = " ".join(str(v) for oid in ids if oid in observations
                           for v in (observations[oid].raw_value, observations[oid].value, observations[oid].period))
        allowed += " " + " ".join(insights[i].narrative for i in theme.insight_ids if i in insights)
        claimed = " ".join([theme.title, theme.question, theme.rationale, *theme.caveats])
        if PresentationPlanValidator._numbers(claimed) - PresentationPlanValidator._numbers(allowed):
            errors.append(f"theme {theme.id} contains unsupported numeric claims")
        signature = (frozenset(ids), frozenset(theme.insight_ids))
        if signature in signatures:
            errors.append(f"theme {theme.id} duplicates another theme's evidence; keep distinct questions within one theme")
        signatures.add(signature)

    seen_slides = set()
    used_themes = set()
    for slide in plan.slides:
        ids = expanded_observation_ids(slide, charts)
        for cid in slide.calculation_ids:
            calc = calculations.get(cid)
            if not calc:
                errors.append(f"slide {slide.id} references unknown or ineligible calculation {cid}")
            elif not set(calc["observation_ids"]) <= ids:
                errors.append(f"slide {slide.id} calculation {cid} is missing its input evidence")
        if slide.theme_id and slide.theme_id not in themes:
            errors.append(f"slide {slide.id} references unknown theme {slide.theme_id}")
        if not plan.themes or slide.slide_type != "analysis":
            continue
        theme = themes.get(slide.theme_id)
        if not theme:
            errors.append(f"analysis slide {slide.id} must reference a planned theme")
            continue
        used_themes.add(theme.id)
        if not slide.analytical_question.strip() or not slide.selection_reason.strip():
            errors.append(f"slide {slide.id} needs an analytical question and evidence selection reason")
        if not ids <= expanded_observation_ids(theme, charts):
            errors.append(f"slide {slide.id} evidence is outside theme {theme.id}")
        s_insights = set(slide.insight_ids) | {iid for b in slide.visual_blocks for iid in b.insight_ids}
        if not s_insights <= set(theme.insight_ids):
            errors.append(f"slide {slide.id} insights are outside theme {theme.id}")
        # Same observations can support a new calculation, but rewriting a title
        # alone does not justify a second analysis page.
        signature = (frozenset(ids), frozenset(s_insights), frozenset(slide.calculation_ids))
        if signature in seen_slides:
            errors.append(f"slide {slide.id} repeats an analysis evidence set without new evidence or calculations")
        seen_slides.add(signature)
        if slide.comparison_mode == "like_for_like":
            selected = [observations[oid] for oid in ids if oid in observations]
            from adaptive_document_agent.services.presentation_evidence import evidence_groups
            groups = evidence_groups(selected)
            units = {(o.unit, o.currency) for o in selected}
            scopes = {(o.entity, o.ifrs_status, o.period_basis, o.period_type) for o in selected}
            period_sets = {frozenset(o.period for o in g) for g in groups}
            from adaptive_document_agent.document_model.period_semantic_validator import classify_period
            if (len(units) != 1 or len(scopes) != 1 or len(period_sets) != 1
                    or any(o.unit in {None, "", "generic", "unknown"} or classify_period(o.period).period_type == "generic" for o in selected)):
                errors.append(f"slide {slide.id} like-for-like comparison has incompatible units, scope or periods")
    for tid in themes.keys() - used_themes:
        errors.append(f"theme {tid} has no analysis slide")
    return errors
