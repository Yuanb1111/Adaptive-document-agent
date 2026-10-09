"""Exact audience-copy localization; analytical values and source grids stay intact."""

import re
from collections import Counter

from .text_capacity import wrap_copy


def text_frames(presentation):
    for slide in presentation.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                yield shape.text_frame, shape.width.inches, shape.height.inches
            elif shape.has_table and not shape.name.startswith('customization:source_table:'):
                for row in shape.table.rows:
                    for cell, column in zip(row.cells, shape.table.columns):
                        yield cell.text_frame, column.width.inches, row.height.inches


def translatable(text):
    # Periods, source values and identifiers remain literal. A reader-facing
    # sentence with numbers remains eligible, with exact numeric validation.
    return bool(re.search(r'[A-Za-z\u3400-\u9fff]', text) and not re.fullmatch(
        r'(?:FY|[QH][1-4]|[1-9]M)?[\d\s.,()\-+%*/:]+(?:[A-Za-z]{1,3})?\*?', text)
        and not re.fullmatch(r'(?:RMB|USD|HKD|EUR|GBP|CNY|US\$|HK\$|[$€£¥])?\s*[-+()\d.,]+\s*[mbx%]?', text))


def audience_copy(presentation):
    return list(dict.fromkeys(frame.text for frame, _, _ in text_frames(presentation)
                              if frame.text.strip() and translatable(frame.text)))


def translation_errors(source, translated):
    if not translated.strip():
        return ['Empty localized copy']
    from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator
    # Sets alone allow deletion of a repeated amount. Count every literal token.
    number = r'(?<![\d.])(?:\([-+]?\d[\d,]*(?:\.\d+)?%?\)|[-+]?\d[\d,]*(?:\.\d+)?%?)'
    if (Counter(re.findall(number, source)) != Counter(re.findall(number, translated))
            or PresentationPlanValidator._numbers(source) != PresentationPlanValidator._numbers(translated)):
        return ['Localized copy changed a number, period or sign']
    if source.count('%') != translated.count('%'):
        return ['Localized copy changed a percentage unit']
    unit = r'(?<![A-Za-z])(?:RMB|USD|HKD|CNY|EUR|GBP|millions?|billions?|thousands?|bps|pp)(?![A-Za-z])'
    if Counter(re.findall(unit, source, re.IGNORECASE)) != Counter(re.findall(unit, translated, re.IGNORECASE)):
        return ['Localized copy changed or invented a literal currency or scale']
    return []


def apply_report_language(presentation, result):
    requirements = result.profile.report_requirements
    if not requirements or not requirements.copy_translations:
        return
    mapping = requirements.copy_translations
    for frame, width, height in text_frames(presentation):
        source = frame.text
        if source not in mapping:
            continue
        translated = mapping[source]
        errors = translation_errors(source, translated)
        if errors:
            raise ValueError('; '.join(errors))
        paragraphs = list(frame.paragraphs)
        size = max((run.font.size.pt for p in paragraphs for run in p.runs if run.font.size), default=
                   max((p.font.size.pt for p in paragraphs if p.font.size), default=14))
        if len(wrap_copy(translated, max(.1, width - .12), size)) * size * 1.25 / 72 > height + .06:
            # Preserve the whole source copy; a failed language requirement is
            # visible in its own report, never hidden by truncation/shrinkage.
            continue
        first = paragraphs[0]
        if first.runs:
            first.runs[0].text = translated
            for run in first.runs[1:]:
                run.text = ''
        else:
            first.text = translated
        for paragraph in paragraphs[1:]:
            paragraph.text = ''
