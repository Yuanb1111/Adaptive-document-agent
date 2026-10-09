"""Put source definitions and model-authored caveats beside their evidence."""


def slide_context_notes(result, slide, charts, index, *, definitions=None):
    from .presentation_ratio_definitions import ratio_definitions
    from .presentation_labels import qualified_metric_name

    notes = []
    definitions = definitions if definitions is not None else ratio_definitions(result) if charts else []
    for chart in charts:
        ids = set(chart.observation_ids)
        bound = [definition for definition in definitions
                 if ids and ids <= set(definition["observation_ids"])]
        if len(bound) == 1:
            definition = bound[0]
            label = qualified_metric_name(index.get(chart.observation_ids[0]))
            factor = f" × {definition['multiplier']:g}" if definition.get("multiplier") is not None else ""
            notes.append(f"{label}: {definition['numerator']} / {definition['denominator']}{factor}.")
    plan = result.presentation_plan
    if plan and slide.theme_id:
        first = next((page for page in plan.slides
                      if page.slide_type == "analysis" and page.theme_id == slide.theme_id), None)
        theme = next((theme for theme in plan.themes if theme.id == slide.theme_id), None)
        if first is not None and first.id == slide.id and theme is not None:
            for caveat in theme.caveats:
                # This generated sentence repeats the matrix's own scope and
                # is not an additional limitation or source definition.
                if caveat == "Displayed composition covers the validated selected-category matrix for its cited periods.":
                    continue
                if caveat.strip():
                    import re
                    if re.fullmatch(r'Interim results are unaudited and separate from annual periods\.?', caveat.strip(), re.I):
                        notes.append('Interim and annual periods are shown separately. '
                                     'Unaudited markers apply only to the identified source columns.')
                    else:
                        notes.append(caveat.strip())
    return list(dict.fromkeys(notes))
