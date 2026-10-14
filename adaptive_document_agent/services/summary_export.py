"""Verify source-part coverage against visible native introductory slide copy."""
import json

from .source_quotes import normalize_quote
from .display_copy_tokens import display_text

_PREFIX = 'ADA_SUMMARY_ITEM_V2:'


def bind_summary_items(slide, page):
    bind_summary_pages([slide], page)


def bind_summary_pages(slides, page, *, texts=None):
    """A logical introductory page may occupy several complete-item slides."""
    from collections import defaultdict, Counter
    bodies = defaultdict(list)
    ordered = []
    for slide in slides:
        for shape in slide.shapes:
            if shape.has_text_frame and shape.name=='brief:body':
                if not normalize_quote(display_text(shape.text)):
                    raise ValueError('Summary native body is empty: ' + page.id)
                bodies[normalize_quote(display_text(shape.text))].append(shape)
                ordered.append(shape)
    texts = texts if texts is not None else [item.text for item in page.items]
    expected = Counter(normalize_quote(display_text(text)) for text in texts)
    bindings = []
    if expected == Counter({key:len(values) for key,values in bodies.items()}):
        bindings = [[bodies[normalize_quote(display_text(text))].pop(0)] for text in texts]
    else:
        # Native geometry can split an already paginated paragraph again when
        # a long title consumes extra height. Bind every visible continuation;
        # the ordered union must still equal the complete authored item.
        offset = 0
        for text in texts:
            target = normalize_quote(display_text(text))
            segments = []
            while offset < len(ordered):
                segments.append(ordered[offset]); offset += 1
                combined = normalize_quote(display_text(' '.join(shape.text for shape in segments)))
                if combined == target:
                    bindings.append(segments)
                    break
                if not target.startswith(combined):
                    break
            else:
                combined = ''
            if combined != target:
                raise ValueError('Summary fact lacks complete ordered visible native copy: ' + page.id)
        if offset != len(ordered):
            raise ValueError('Summary native copy has unbound extra text: ' + page.id)
    for index, item in enumerate(page.items):
        for segment_index, shape in enumerate(bindings[index]):
            properties = shape.element.xpath('.//p:cNvPr')[0]
            properties.set('descr', _PREFIX + json.dumps({'page_id': page.id, 'item_index': index,
                'part_ids': item.part_ids, 'segment_index': segment_index,
                'segment_count': len(bindings[index])}, ensure_ascii=False))


def verify_summary_export(presentation, result):
    if not result.presentation_plan or result.presentation_plan.company.summary_review is None:
        return {}
    company = result.presentation_plan.company
    pages = {p.id: p for p in company.summary_pages}
    mapping = result.profile.report_requirements.copy_translations if result.profile.report_requirements else {}
    localized = result.profile.report_requirements.summary_copy_translations if result.profile.report_requirements else {}
    used, seen, body_slides, segments = {}, set(), set(), {}
    for number, slide in enumerate(presentation.slides, 1):
        for shape in slide.shapes:
            properties = shape.element.xpath('.//p:cNvPr')
            marker = properties[0].get('descr', '') if properties else ''
            if not marker.startswith(_PREFIX):
                continue
            record = json.loads(marker[len(_PREFIX):])
            page = pages.get(record['page_id'])
            index = record['item_index']
            if page is None or type(index) is not int or not 0 <= index < len(page.items):
                raise ValueError('Unknown exported introductory item')
            item = page.items[index]
            from .localized_summary_copy import summary_item_copy
            identity = page.id, index
            segment_index, segment_count = record.get('segment_index', 0), record.get('segment_count', 1)
            if (type(segment_index) is not int or type(segment_count) is not int
                    or not 0 <= segment_index < segment_count
                    or record['part_ids'] != item.part_ids):
                raise ValueError('Duplicate or changed exported introductory evidence binding')
            existing = segments.setdefault(identity, [])
            if segment_index != len(existing) or any(count != segment_count for _, count in existing):
                raise ValueError('Missing, duplicate or reordered introductory continuation')
            seen.add(identity)
            if page.placement == 'body':
                body_slides.add(number)
            if not shape.has_text_frame or shape.name != 'brief:body':
                raise ValueError('Introductory evidence is missing from visible native slide copy')
            existing.append((shape.text, segment_count))
            for pid in item.part_ids:
                used.setdefault(pid, []).append(number)
    expected_items = {(page.id, i) for page in company.summary_pages for i in range(len(page.items))}
    required = {p.id for p in company.summary_review.parts if p.role == 'content'}
    if seen != expected_items or not required <= used.keys():
        raise ValueError('Exported introduction does not cover every substantive source part')
    for (page_id, index), values in segments.items():
        page, item = pages[page_id], pages[page_id].items[index]
        expected = {normalize_quote(display_text(summary_item_copy(result, page, index)))}
        if f'{page_id}:{index}' not in localized:
            expected.add(normalize_quote(display_text(mapping.get(item.text, item.text))))
        if (len(values) != values[0][1] or
                normalize_quote(display_text(' '.join(text for text, _ in values))) not in expected):
            raise ValueError('Introductory evidence is missing from visible native slide copy or its complete continuation')
    limit = company.summary_review.max_intro_slides
    if limit is not None and len(body_slides)>limit:
        raise ValueError(f'Exported company introduction exceeds its {limit}-page limit')
    for record in result.presentation_export_trace:
        if record['planned_slide_id'] in {s.id for s in result.presentation_plan.slides if s.slide_type == 'company_overview'}:
            record['summary_part_ids'] = sorted(pid for pid, numbers in used.items()
                                                if set(numbers).intersection(record['slide_numbers']))
            record['summary_mapping_basis'] = 'verified_visible_native_item_copy'
    return used
