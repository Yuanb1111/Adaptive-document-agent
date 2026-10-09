"""Put source definitions and model-authored caveats beside their evidence."""
import re


def _repeats_definition(copy, definition, *, sole_definition):
    """Recognize complete literal division statements, preserving extra caveats."""
    text = ' '.join(copy.split()).strip().rstrip('.')
    text = re.sub(r'^\(\d+\)\s*', '', text)
    metric, numerator, denominator = (re.escape(' '.join(str(definition[key]).split()))
                                      for key in ('metric', 'numerator', 'denominator'))
    multiplier = r'(?: and multiplied by 100(?:\.0+)?%?)?' if definition.get('multiplier') == 100 else ''
    patterns = [rf'The calculation of {metric} is based on {numerator} divided by {denominator}{multiplier}',
                rf'{metric} is defined as {numerator} divided by {denominator}{multiplier}',
                rf'Calculated by dividing {numerator} by {denominator}{multiplier}']
    if sole_definition:
        patterns.append(rf'Ratio is calculated by dividing {numerator} by {denominator}{multiplier}')
    return any(re.fullmatch(pattern, text, re.I) for pattern in patterns)


def slide_context_notes(result, slide, charts, index, *, definitions=None):
    from .presentation_ratio_definitions import ratio_definitions
    from .presentation_labels import qualified_metric_name

    notes = []
    displayed_definitions = []
    definitions = definitions if definitions is not None else ratio_definitions(result) if charts else []
    for chart in charts:
        ids = set(chart.observation_ids)
        bound = [definition for definition in definitions
                 if ids and ids <= set(definition["observation_ids"])]
        if len(bound) == 1:
            definition = bound[0]
            displayed_definitions.append(definition)
            label = qualified_metric_name(index.get(chart.observation_ids[0]))
            factor = f" × {definition['multiplier']:g}" if definition.get("multiplier") is not None else ""
            notes.append(f"{label}: {definition['numerator']} / {definition['denominator']}{factor}.")
        from .source_row_qualifications import source_row_qualifications
        notes.extend(note['text'] for note in source_row_qualifications(
            [index.get(oid) for oid in chart.observation_ids if index.get(oid)], result.document))
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
                    if re.fullmatch(r"(?:FY|Annual) columns'? audit status (?:is )?unknown\.?", caveat.strip(), re.I):
                        continue  # No affirmative qualifier is supplied; source metadata remains in the audit.
                    if re.fullmatch(r'Interim results are unaudited and separate from annual periods\.?', caveat.strip(), re.I):
                        notes.append('Interim and annual periods are shown separately. '
                                     'Unaudited markers apply only to the identified source columns.')
                    else:
                        notes.append(caveat.strip())
    # Keep the precise, source-bound formula once. Suppress only complete
    # duplicate division statements, never a sentence with an extra condition.
    return list(dict.fromkeys(note for note in notes if not any(
        _repeats_definition(note, definition, sole_definition=len(displayed_definitions) == 1)
        for definition in displayed_definitions)))
