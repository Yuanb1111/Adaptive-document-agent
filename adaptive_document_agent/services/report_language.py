"""Exact audience-copy localization; analytical values and source grids stay intact."""

import re

from .text_capacity import wrap_copy
from .display_copy_tokens import display_text, copy_tokens


def original_language(language):
    return language.strip().casefold() in {'original', 'source', 'original language', '原文', '原始语言'}


def text_frames(presentation):
    for slide in presentation.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                if (shape.name in {'customization:table_label', 'customization:source_section', 'customization:source_footer'}
                        or shape.text.lstrip().lower().startswith('source:')):
                    continue
                yield shape.text_frame, shape.width.inches, shape.height.inches
            elif shape.has_table and not shape.name.startswith('customization:source_table:'):
                for row in shape.table.rows:
                    for cell, column in zip(row.cells, shape.table.columns):
                        yield cell.text_frame, column.width.inches, row.height.inches


def translatable(text):
    # Periods, source values and identifiers remain literal. A reader-facing
    # sentence with numbers remains eligible, with exact numeric validation.
    from .executive_brief import _UNIT_ONLY_LABEL
    if re.fullmatch(r'(?i)[+\-]?\s*(?:RMB|USD|HKD|EUR|GBP|CNY|US\$|HK\$)\s*[-+()\d.,]+\s*(?:[mkb]|bn|mn|thousand|million|billion)',text):
        return False
    if (_UNIT_ONLY_LABEL.fullmatch(text) or re.fullmatch(
            r'\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}\*?', text, re.I)):
        return False
    return bool(re.search(r'[A-Za-z\u3400-\u9fff]', text) and not re.fullmatch(
        r'(?:FY|[QH][1-4]|[1-9]M)?[\d\s.,()\-+%*/:]+(?:[A-Za-z]{1,3})?\*?', text)
        and not re.fullmatch(r'(?:RMB|USD|HKD|EUR|GBP|CNY|US\$|HK\$|[$€£¥])?\s*[-+()\d.,]+\s*[mbx%]?', text))


def audience_copy(presentation):
    values = [frame.text for frame, _, _ in text_frames(presentation)]
    values.extend(element.text or '' for element in chart_display_strings(presentation))
    return list(dict.fromkeys(display_text(value) for value in values if value.strip() and translatable(value)))


def copy_limits(presentation):
    """Conservative character budgets for CJK translation in existing native boxes."""
    limits = {}
    for frame, width, height in text_frames(presentation):
        size = max((r.font.size.pt for p in frame.paragraphs for r in p.runs if r.font.size), default=
                   max((p.font.size.pt for p in frame.paragraphs if p.font.size), default=14))
        capacity = max(1, int(max(.1, width - .17) * 72 / size) * int((height + .06) * 72 / (size * 1.25)))
        text = display_text(frame.text)
        limits[text] = min(limits.get(text, capacity), capacity)
    return limits


def copy_fit_errors(presentation, source, translated):
    for frame, width, height in text_frames(presentation):
        if display_text(frame.text) == source and not _fits(frame, width, height, display_text(translated)):
            return ['Localized copy exceeds its readable native text box; compact prose without omitting facts']
    return []


def fit_translation(presentation, source, translated):
    from .display_copy_tokens import compact_display_periods, compact_display_units
    text = display_text(translated)
    if translation_errors(source,text):
        return text
    for compact in (compact_display_periods,compact_display_units):
        if not copy_fit_errors(presentation,source,text):
            break
        candidate = compact(text)
        if not translation_errors(source,candidate):
            text = candidate
    return text


def _fits(frame, width, height, text):
    size = max((run.font.size.pt for p in frame.paragraphs for run in p.runs if run.font.size), default=
               max((p.font.size.pt for p in frame.paragraphs if p.font.size), default=14))
    return len(wrap_copy(text, max(.1, width - .12), size)) * size * 1.25 / 72 <= height + .06


def chart_display_strings(presentation):
    """Native display caches only; original embedded Excel source stays literal."""
    for slide in presentation.slides:
        for shape in slide.shapes:
            if shape.has_chart:
                yield from shape.chart._chartSpace.xpath('.//c:strCache/c:pt/c:v')


def translation_errors(source, translated):
    if not translated.strip():
        return ['Empty localized copy']
    original, target = copy_tokens(source), copy_tokens(translated)
    if original[:3] != target[:3] or original[4] != target[4]:
        return ['Localized copy changed a number, period or sign']
    if original[3] != target[3] or original[5] != target[5]:
        return ['Localized copy changed or invented a literal currency or scale']
    return []


def apply_report_language(presentation, result):
    requirements = result.profile.report_requirements
    if not requirements or not requirements.copy_translations:
        return
    mapping = {display_text(k): display_text(v) for k,v in requirements.copy_translations.items()}
    for frame, width, height in text_frames(presentation):
        source = display_text(frame.text)
        if source not in mapping:
            continue
        translated = mapping[source]
        errors = translation_errors(source, translated)
        if errors:
            raise ValueError('; '.join(errors))
        paragraphs = list(frame.paragraphs)
        if not _fits(frame, width, height, translated):
            # Preserve the whole source copy; a failed language requirement is
            # visible in its own report, never hidden by truncation/shrinkage.
            continue
        from copy import deepcopy
        first = paragraphs[0]
        properties = deepcopy(first._p.pPr) if first._p.pPr is not None else None
        run_properties = deepcopy(first.runs[0]._r.rPr) if first.runs and first.runs[0]._r.rPr is not None else None
        frame.clear()
        for i, line in enumerate(translated.split('\n')):
            paragraph = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
            if properties is not None:
                if paragraph._p.pPr is not None:
                    paragraph._p.remove(paragraph._p.pPr)
                paragraph._p.insert(0, deepcopy(properties))
            run = paragraph.add_run(); run.text = line
            if run_properties is not None:
                run._r.insert(0, deepcopy(run_properties))
    for element in chart_display_strings(presentation):
        source = display_text(element.text or '')
        if source in mapping:
            if translation_errors(source, mapping[source]):
                raise ValueError('Localized chart label changed source numbers or units')
            element.text = mapping[source]
