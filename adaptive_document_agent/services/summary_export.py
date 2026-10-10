"""Verify source-part coverage against visible native introductory slide copy."""
import json

from .source_quotes import normalize_quote

_PREFIX = 'ADA_SUMMARY_ITEM_V2:'


def bind_summary_items(slide, page):
    bind_summary_pages([slide], page)


def bind_summary_pages(slides, page):
    """A logical introductory page may occupy several complete-item slides."""
    for index, item in enumerate(page.items):
        shapes = [s for slide in slides for s in slide.shapes if s.has_text_frame
                  and normalize_quote(s.text) == normalize_quote(item.text)
                  and s.name == 'brief:body']
        if len(shapes) != 1:
            raise ValueError('Summary fact lacks one complete visible native body: ' + page.id)
        properties = shapes[0].element.xpath('.//p:cNvPr')[0]
        properties.set('descr', _PREFIX + json.dumps({'page_id': page.id, 'item_index': index,
                                                     'part_ids': item.part_ids}, ensure_ascii=False))


def verify_summary_export(presentation, result):
    if not result.presentation_plan or result.presentation_plan.company.summary_review is None:
        return {}
    company = result.presentation_plan.company
    pages = {p.id: p for p in company.summary_pages}
    mapping = result.profile.report_requirements.copy_translations if result.profile.report_requirements else {}
    used, seen = {}, set()
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
            identity = page.id, index
            if identity in seen or record['part_ids'] != item.part_ids:
                raise ValueError('Duplicate or changed exported introductory evidence binding')
            seen.add(identity)
            expected = {normalize_quote(item.text), normalize_quote(mapping.get(item.text, item.text))}
            if not shape.has_text_frame or normalize_quote(shape.text) not in expected:
                raise ValueError('Introductory evidence is missing from visible native slide copy')
            for pid in item.part_ids:
                used.setdefault(pid, []).append(number)
    expected_items = {(page.id, i) for page in company.summary_pages for i in range(len(page.items))}
    required = {p.id for p in company.summary_review.parts if p.role == 'content'}
    if seen != expected_items or not required <= used.keys():
        raise ValueError('Exported introduction does not cover every substantive source part')
    for record in result.presentation_export_trace:
        if record['planned_slide_id'] in {s.id for s in result.presentation_plan.slides if s.slide_type == 'company_overview'}:
            record['summary_part_ids'] = sorted(pid for pid, numbers in used.items()
                                                if set(numbers).intersection(record['slide_numbers']))
            record['summary_mapping_basis'] = 'verified_visible_native_item_copy'
    return used
