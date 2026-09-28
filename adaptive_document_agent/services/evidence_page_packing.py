"""Stack small evidence tables while retaining each table's own headers."""

from copy import deepcopy


def pack_evidence_pages(presentation, slides):
    """Only combine explicitly marked, adjacent evidence-only pages.

    Numeric cells, units, period headers, citations and source notes survive
    unchanged. A visible gap separates the tables; no cross-period join occurs.
    """
    from pptx.util import Inches
    retained = []
    for slide in slides:
        tables = [s for s in slide.shapes if s.name.startswith("evidence:packable")]
        if not retained or len(tables) != 1:
            retained.append(slide)
            continue
        previous = retained[-1]
        old_tables = [s for s in previous.shapes if s.name.startswith("evidence:packable")]
        if not old_tables or len(old_tables) >= 2:
            retained.append(slide)
            continue
        top = max(s.top.inches + s.height.inches for s in old_tables) + .32
        if top + tables[0].height.inches > min(5.65, presentation.slide_height.inches - 1.35):
            retained.append(slide)
            continue
        element = deepcopy(tables[0]._element)
        for prop in element.xpath(".//p:cNvPr"):
            prop.set("id", str(previous.shapes._next_shape_id))
        previous.shapes._spTree.insert_element_before(element, "p:extLst")
        moved = previous.shapes[-1]
        moved.name = f"evidence:packable:{moved.shape_id}"
        moved.top = Inches(top)
        for name in ("evidence:footer", "evidence:convention"):
            old = next((s for s in previous.shapes if s.name == name), None)
            new = next((s for s in slide.shapes if s.name == name), None)
            if new is None:
                continue
            if old is None:
                copied = deepcopy(new._element)
                for prop in copied.xpath(".//p:cNvPr"):
                    prop.set("id", str(previous.shapes._next_shape_id))
                previous.shapes._spTree.insert_element_before(copied, "p:extLst")
            elif new.text != old.text:
                paragraph = old.text_frame.add_paragraph()
                paragraph.text = new.text
                paragraph.font.size = old.text_frame.paragraphs[0].font.size
                old.height = Inches(.48)
        previous.notes_slide.notes_text_frame.text += "\n\n" + slide.notes_slide.notes_text_frame.text
        for slide_id in list(presentation.slides._sldIdLst):
            if presentation.part.related_slide(slide_id.rId) is slide:
                presentation.part.drop_rel(slide_id.rId)
                presentation.slides._sldIdLst.remove(slide_id)
                break
    # python-pptx allocates the next slide filename from the slide count.
    # Removing a middle page leaves a hole; renumber before later pages are
    # appended so an existing slide part can never be overwritten in the ZIP.
    presentation.part.rename_slide_parts(s.rId for s in presentation.slides._sldIdLst)
    return retained
