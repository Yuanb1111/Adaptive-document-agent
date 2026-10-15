"""Separate renderer-authored source indexes from all audience body pages."""

DATA_INDEX_TAG = 'ada:data-index'


def data_index_slide_numbers(presentation, result):
    """Analytical/introductory provenance overrides an incorrect appendix tag."""
    candidates = {n for n, slide in enumerate(presentation.slides, 1)
                  if slide.element.cSld.get('name') == DATA_INDEX_TAG}
    if result.presentation_plan:
        body_ids = {s.id for s in result.presentation_plan.slides if s.slide_type != 'appendix'}
        candidates -= {n for record in result.presentation_export_trace
                       if record.get('planned_slide_id') in body_ids for n in record['slide_numbers']}
    from .summary_export import _PREFIX
    return sorted(n for n in candidates if not any(
        (properties := shape.element.xpath('.//p:cNvPr'))
        and properties[0].get('descr', '').startswith(_PREFIX)
        for shape in presentation.slides[n - 1].shapes))


def slide_counts(presentation, result):
    index_count = len(data_index_slide_numbers(presentation, result))
    return {'total': len(presentation.slides), 'body': len(presentation.slides) - index_count,
            'data_index': index_count}


def place_data_index_after_body(presentation, result):
    """Reorder only genuine source pages; never move analytical continuations."""
    index_numbers = set(data_index_slide_numbers(presentation, result))
    order = [n for n in range(1, len(presentation.slides) + 1) if n not in index_numbers] + sorted(index_numbers)
    if order == list(range(1, len(presentation.slides) + 1)):
        return
    identifiers = list(presentation.slides._sldIdLst)
    for element in identifiers:
        presentation.slides._sldIdLst.remove(element)
    for number in order:
        presentation.slides._sldIdLst.append(identifiers[number - 1])
    from .presentation_export_trace import rebase_trace
    rebase_trace(presentation, result, {old: new for new, old in enumerate(order, 1)})
