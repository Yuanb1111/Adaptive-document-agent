"""Whole-claim localization with immutable introductory evidence locators."""
import re

from .display_copy_tokens import display_text


def summary_copy_units(result) -> list[dict]:
    if result.presentation_plan is None:
        return []
    units, groups = [], {}
    for page in result.presentation_plan.company.summary_pages:
        for index, item in enumerate(page.items):
            key = item.continuation_group or f'{page.id}:{index}'
            if key not in groups:
                groups[key] = {'source': '', 'parts': [], 'slots': []}
                units.append(groups[key])
            unit = groups[key]
            unit['parts'].append((item.continuation_index, display_text(item.text)))
            unit['slots'].append((item.continuation_index, f'{page.id}:{index}'))
    for unit in units:
        unit['parts'].sort()
        unit['slots'].sort()
        unit['source'] = ''.join(text for _, text in unit['parts'])
    return units


def retain_summary_translations(result, units: list[dict], accepted: dict[str, str]) -> None:
    """Layout subdivisions never authorize independent or rewritten claims."""
    localized = {}
    for unit in units:
        translated = accepted.get(unit['source'])
        if translated is None:
            continue
        count = len(unit['slots'])
        # Keep the original evidence binding cardinality. The native renderer
        # sizes each translated item before placing it, with no shrinking.
        if len(translated) < count:
            raise ValueError('Translated claim cannot cover every original evidence locator')
        boundaries = [match.end() for match in re.finditer(r'\s+|[。；;！？!?，、]|,(?!\d)', translated)]
        cuts = [0]
        for index in range(1, count):
            target = index * len(translated) // count
            candidates = [cut for cut in boundaries if cuts[-1] < cut <= len(translated)-(count-index)]
            cuts.append(min(candidates, key=lambda cut: abs(cut-target)) if candidates else
                        max(cuts[-1]+1, min(target,len(translated)-(count-index))))
        cuts.append(len(translated))
        pieces = [translated[a:b] for a, b in zip(cuts,cuts[1:])]
        if not all(piece.strip() for piece in pieces):
            # Equal proportional boundaries also cover very short final parts.
            cuts = [i * len(translated) // count for i in range(count + 1)]
            pieces = [translated[a:b] for a, b in zip(cuts, cuts[1:])]
        if ''.join(pieces) != translated or not all(piece.strip() for piece in pieces):
            raise ValueError('Localized claim lost its complete display copy')
        localized.update({slot: piece for (_, slot), piece in zip(unit['slots'], pieces)})
    result.profile.report_requirements.summary_copy_translations = localized


def summary_item_copy(result, page, index: int) -> str:
    requirements = result.profile.report_requirements
    return (requirements.summary_copy_translations.get(f'{page.id}:{index}', page.items[index].text)
            if requirements else page.items[index].text)


def verify_summary_translations(result) -> None:
    requirements = result.profile.report_requirements
    if not requirements or not requirements.summary_copy_translations:
        return
    from .report_language import translation_errors
    known = set()
    for unit in summary_copy_units(result):
        slots = [slot for _, slot in unit['slots']]
        known.update(slots)
        populated = [slot for slot in slots if slot in requirements.summary_copy_translations]
        if not populated:
            continue
        text = ''.join(requirements.summary_copy_translations[slot] for slot in slots if slot in populated)
        if (len(populated) != len(slots) or text != requirements.copy_translations.get(unit['source'])
                or translation_errors(unit['source'], text)):
            raise ValueError('Localized Summary changed its complete checked claim or evidence locators')
    if not requirements.summary_copy_translations.keys() <= known:
        raise ValueError('Unknown localized Summary evidence locator')
