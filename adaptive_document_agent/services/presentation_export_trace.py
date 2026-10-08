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
            record=dict(planned_slide_id=slide_plan.id,topic_id=slide_plan.theme_id,
                slide_numbers=list(range(before+1,after+1)),observation_ids=sorted(ids),chart_ids=sorted(chart_ids),
                source_pages=sorted(pages),mapping_basis='renderer_input_scope; not claim-by-claim display proof')
            result.presentation_export_trace.append(record)
            for i in range(before,after):
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
