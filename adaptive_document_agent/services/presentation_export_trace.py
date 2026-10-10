"""Bind renderer input scopes to actual physical slides and durable PPT notes."""
import json
from contextlib import contextmanager


@contextmanager
def record_section(presentation,slide_plan,result):
    before=len(presentation.slides)
    completed=False
    try:
        yield
        completed=True
    finally:
        after=len(presentation.slides)
        if completed and after>before:
            chart_ids=set(slide_plan.chart_ids)|{i for b in slide_plan.visual_blocks for i in b.chart_ids}
            ids=set(slide_plan.observation_ids)|{i for b in slide_plan.visual_blocks for i in b.observation_ids}
            ids.update(i for c in result.charts if c.id in chart_ids for i in [*c.observation_ids,*c.total_observation_ids])
            pages=set(slide_plan.source_pages)|{e.page for o in result.observations if o.id in ids for e in o.evidence}
            if slide_plan.slide_type == 'data_quality':
                # The renderer replaces the planned quality copy with current
                # scope items. Stale planned pages are not their source evidence.
                from .presentation_scope import scope_items
                ids, chart_ids = set(), set()
                pages = {p for item in scope_items(result) for p in item.pages}
            if slide_plan.slide_type == 'company_overview' and result.presentation_plan:
                pages.update(result.presentation_plan.company.source_pages)
            record=dict(planned_slide_id=slide_plan.id,topic_id=slide_plan.theme_id,
                slide_numbers=list(range(before+1,after+1)),observation_ids=sorted(ids),chart_ids=sorted(chart_ids),
                source_pages=sorted(pages),mapping_basis='renderer_input_scope; not claim-by-claim display proof')
            result.presentation_export_trace.append(record)
            for i in range(before,after):
                presentation.slides[i]._ada_section_label = slide_plan.section_title or slide_plan.title
                notes=presentation.slides[i].notes_slide.notes_text_frame
                trace={**record,'physical_slide':i+1}
                try:
                    original=json.loads(notes.text)
                except (ValueError,TypeError):
                    original=None
                if isinstance(original,dict):
                    original['ADA_EXPORT_TRACE_V1']=trace
                    notes.text=json.dumps(original,ensure_ascii=False,indent=2)
                else:
                    notes.text+='\n\nADA_EXPORT_TRACE_V1\n'+json.dumps(trace,ensure_ascii=False)
            coverage=result.profile.source_coverage
            if coverage:
                for section in coverage.sections:
                    section.export_mapping_status='recorded_renderer_scope'
                    if any(section.start_page<=p<=section.end_page for p in pages):
                        if slide_plan.theme_id and slide_plan.theme_id not in section.exported_topic_ids:
                            section.exported_topic_ids.append(slide_plan.theme_id)
                        section.exported_slide_numbers=sorted(set(section.exported_slide_numbers)|set(record['slide_numbers']))


def clear_trace(result):
    result.presentation_export_trace=[]
    if result.profile.source_coverage:
        for section in result.profile.source_coverage.sections:
            section.export_mapping_status='not_recorded'
            section.exported_topic_ids=[];section.exported_slide_numbers=[]


def rebase_trace(presentation, result, number_map):
    """Keep durable source mappings accurate after folding physical pages."""
    by_page = {}
    for record in result.presentation_export_trace:
        record['slide_numbers'] = sorted({number_map[n] for n in record['slide_numbers']})
        for number in record['slide_numbers']:
            by_page.setdefault(number, []).append({**record, 'physical_slide': number})
    if result.profile.source_coverage:
        for section in result.profile.source_coverage.sections:
            section.exported_slide_numbers = sorted({number_map[n] for n in section.exported_slide_numbers})
    for number, records in by_page.items():
        notes = presentation.slides[number - 1].notes_slide.notes_text_frame
        # Preserve the old audit record explicitly as historical. Append the
        # current mapping after all merged notes so readers find current IDs.
        primary = next((r for r in records if r.get('topic_id')), records[0])
        current = {**primary, 'co_located_scopes': records}
        try:
            structured = json.loads(notes.text)
        except (ValueError, TypeError):
            structured = None
        if isinstance(structured, dict):
            previous = structured.pop('ADA_EXPORT_TRACE_V1', None)
            if previous is not None:
                structured.setdefault('ADA_PRIOR_EXPORT_TRACES_V1', []).append(previous)
            structured['ADA_EXPORT_TRACE_V1'] = current
            notes.text = json.dumps(structured, ensure_ascii=False, indent=2)
        else:
            notes.text = notes.text.replace('ADA_EXPORT_TRACE_V1', 'ADA_PRIOR_EXPORT_TRACE_V1')
            notes.text += '\n\nADA_EXPORT_TRACE_V1\n' + json.dumps(current, ensure_ascii=False)
