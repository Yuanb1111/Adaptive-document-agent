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
                        or shape.name.startswith('customization:source_footnote:')
                        or shape.text.lstrip().lower().startswith(('source:','来源：'))):
                    continue
                yield shape.text_frame, shape.width.inches, shape.height.inches
            elif shape.has_table and not shape.name.startswith('customization:source_table:'):
                for row in shape.table.rows:
                    for cell, column in zip(row.cells, shape.table.columns):
                        yield cell.text_frame, column.width.inches, row.height.inches


def translatable(text):
    # Periods, source values and identifiers remain literal. A reader-facing
    # sentence with numbers remains eligible, with exact numeric validation.
    if re.fullmatch(r'(?i)[+\-]?\s*(?:RMB|USD|HKD|EUR|GBP|CNY|US\$|HK\$)\s*[-+()\d.,]+\s*(?:[mkb]|bn|mn|thousand|million|billion)',text):
        return False
    if (re.fullmatch(
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
    if display_text(source) == display_text(translated):
        return []  # Existing native copy is checked by normal export preflight.
    # Inventory geometry once. The inventory deck is immutable during review;
    # scanning every slide for every string made localization quadratic.
    index = getattr(presentation, '_ada_copy_geometry', None)
    if index is None:
        index = {}
        for frame, width, height in text_frames(presentation):
            index.setdefault(display_text(frame.text), []).append((frame, width, height))
        presentation._ada_copy_geometry = index
    if source in getattr(presentation, '_ada_reflow_copy', set()):
        return []  # Native introduction layout paginates the translated copy.
    for frame, width, height in index.get(source, []):
        if not _fits(frame, width, height, display_text(translated)):
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
    if (re.search(r'(?i)\b(?:indebtedness|total\s+debt)\b',source)
            and not re.search(r'(?i)\bliabilit(?:y|ies)\b',source)
            and '总负债' in translated):
        return ['Localized copy conflates debt/indebtedness with total liabilities']
    return []


def requested_language_errors(translated, language):
    """Unambiguous monetary unit words are prose, not retained proper names."""
    if not re.search(r'(?i)中文|chinese|^zh(?:-|$)', language):
        return []
    from .executive_brief import _MONEY_QUANTITY
    if any((match['prefix'] or match['suffix']) and
           match['unit'].casefold() in {'million','billion','trillion','thousand'}
           for match in _MONEY_QUANTITY.finditer(translated)):
        return ['Chinese display copy retains an untranslated monetary scale word']
    return []


def apply_report_language(presentation, result):
    requirements = result.profile.report_requirements
    if not requirements or not requirements.copy_translations:
        return
    mapping = {display_text(k): display_text(v) for k,v in requirements.copy_translations.items()}
    chinese = any(r.kind=='output_language' and r.resolution=='resolved' and r.language_scope in {'body','all'}
                  and re.search(r'(?i)中文|chinese|^zh(?:-|$)',r.language) for r in requirements.items)
    # Native chart wrapping may happen after inventory capture. Rebind only
    # whitespace-equivalent, unambiguous strings; never use fuzzy matching.
    wrapped = {}
    for key, value in mapping.items():
        compact = ' '.join(key.split())
        wrapped.setdefault(compact, set()).add(value)
    def translation(source, *, heading=False):
        if source in mapping:
            return mapping[source]
        values = wrapped.get(' '.join(source.split()), set())
        if len(values) == 1:
            return next(iter(values))
        if chinese and source.endswith(' (continued)'):
            base = source.removesuffix(' (continued)')
            if base in mapping:
                return mapping[base] + '（续）'
        if heading:
            match = re.fullmatch(r'(\d{2}\s+)(.+)', source, flags=re.S)
            if match and match[2] in mapping:
                return match[1] + mapping[match[2]]
        return None
    for frame, width, height in text_frames(presentation):
        source = display_text(frame.text)
        translated = translation(source, heading=getattr(frame._parent, 'name', '')=='brief:heading')
        if translated is None:
            continue
        errors = translation_errors(source, translated)
        if errors:
            raise ValueError('; '.join(errors))
        paragraphs = list(frame.paragraphs)
        if translated != source and not _fits(frame, width, height, translated):
            # Preserve the whole source copy; a failed language requirement is
            # visible in its own report, never hidden by truncation/shrinkage.
            continue
        # Pagination can change an ordinal/continuation wrapper. Only compose
        # checked base copy with a native UI marker; keep exact numeric checks
        # and successful fitting, then expose the derived binding to coverage.
        if source not in mapping:
            requirements.copy_translations[source] = translated
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
        translated = translation(source)
        if translated is not None:
            if translation_errors(source, translated):
                raise ValueError('Localized chart label changed source numbers or units')
            element.text = translated
    localize_source_wrappers(presentation, result)


def localize_source_wrappers(presentation, result):
    """Translate standard UI provenance labels; literal source annotations stay intact."""
    requirements = result.profile.report_requirements
    if not requirements or not any(r.kind=='output_language' and r.resolution=='resolved'
        and r.language_scope in {'body','all'} and re.search(r'(?i)中文|chinese|^zh(?:-|$)',r.language)
        for r in requirements.items):
        return
    for slide in presentation.slides:
        for shape in slide.shapes:
            if not shape.has_text_frame or shape.name.startswith('customization:source_footnote:'):
                continue
            for paragraph in shape.text_frame.paragraphs:
                for run in paragraph.runs:
                    run.text = re.sub(r'Source: Document disclosures \(p\. ([\d, -]+)\)',
                        lambda m:'来源：文件披露（PDF 第 '+m[1]+' 页）',run.text)
                    run.text = run.text.replace('Source: Document disclosures (page references not available)',
                                               '来源：文件披露（无可用页码）')
                    run.text = re.sub(r'Source image: document p\. (\d+)',
                                      lambda m: '来源图片：PDF 第 ' + m[1] + ' 页', run.text)
                    if shape.name in {'customization:table_label','customization:source_footer'}:
                        run.text = re.sub(r'Source table (\d+) \(PDF page (\d+)\)',
                            lambda m:'原始表格 '+m[1]+'（PDF 第 '+m[2]+' 页）',run.text)
                        run.text = run.text.replace('Original header text and context in notes.', '原始表头与上下文见备注。')
