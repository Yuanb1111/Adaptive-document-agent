"""Decoded page glyphs and ruling geometry in the text's reading orientation.

PDFium supplies Unicode for fonts whose MuPDF/pdfminer mappings are incomplete.
MuPDF supplies vector rules. No document content is interpreted or executed.
"""
from collections import Counter
from dataclasses import dataclass
from math import pi


@dataclass
class Glyph:
    text: str
    left: float
    top: float
    right: float
    bottom: float
    size: float


@dataclass
class GeometryLine:
    words: list[Glyph]
    top: float
    bottom: float
    size: float

    @property
    def text(self):
        return ' '.join(w.text for w in self.words)


def rotate_point(x, y, width, height, rotation):
    if rotation == 90:
        return height-y, x
    if rotation == 180:
        return width-x, height-y
    if rotation == 270:
        return y, width-x
    return x,y


def rotate_box(box, width, height, rotation):
    a,b,c,d=box
    points=[rotate_point(x,y,width,height,rotation) for x,y in ((a,b),(a,d),(c,b),(c,d))]
    return min(x for x,y in points),min(y for x,y in points),max(x for x,y in points),max(y for x,y in points)


def page_geometry(textpage, page, *, rotation=None):
    import pypdfium2.raw as raw
    from statistics import median
    width,height=page.rect.width,page.rect.height
    source_left,_,_,source_top=textpage.page.get_bbox()
    characters=[]
    current=[]
    def flush():
        if current:
            direction=current[0][0]
            characters.append((direction,''.join(c[1] for c in current),
                (min(c[2][0] for c in current),min(c[2][1] for c in current),
                 max(c[2][2] for c in current),max(c[2][3] for c in current)),
                median(c[3] for c in current)))
            current.clear()
    for index in range(textpage.count_chars()):
        code=raw.FPDFText_GetUnicode(textpage,index)
        if not code or code<32 or chr(code).isspace():
            flush()
            continue
        angle=raw.FPDFText_GetCharAngle(textpage,index)
        direction=(round(angle/(pi/2))*90)%360
        left,bottom,right,top=textpage.get_charbox(index)
        size=raw.FPDFText_GetFontSize(textpage,index)
        if current and direction!=current[0][0]:
            flush()
        box=(left-source_left,source_top-top,right-source_left,source_top-bottom)
        if current:
            prior=rotate_box(current[-1][2],width,height,(-direction)%360)
            following=rotate_box(box,width,height,(-direction)%360)
            if following[0]-prior[2]>5.5:
                flush()  # Separately drawn cells can lack PDFium-generated spaces.
        current.append((direction,chr(code),box,size))
    flush()
    if rotation is None:
        rotation=Counter(direction for direction,_,_,_ in characters).most_common(1)[0][0] if characters else 0
    # A 270-degree source angle corresponds to upward text; rotate it clockwise.
    turn=(-rotation)%360
    glyphs=[]
    for direction,text,box,size in characters:
        if direction!=rotation:
            continue
        left,top,right,bottom=rotate_box(box,width,height,turn)
        glyphs.append(Glyph(text,left,top,right,bottom,max(1,bottom-top)))
    groups=[]
    for glyph in sorted(glyphs,key=lambda g:((g.top+g.bottom)/2,g.left)):
        center=(glyph.top+glyph.bottom)/2
        if not groups or abs(center-median((g.top+g.bottom)/2 for g in groups[-1]))>max(2.2,glyph.size*.3):
            groups.append([])
        groups[-1].append(glyph)
    # Font sizes in PDFium can be an unscaled Tf=1; use MuPDF's transformed
    # span sizes for reliable distinction between source notes and body prose.
    fonts=[]
    for block in page.get_text('dict')['blocks']:
        for line in block.get('lines',[]):
            for span in line['spans']:
                box=rotate_box(tuple(span['bbox']),width,height,turn)
                fonts.append(((box[1]+box[3])/2,span['size']))
    lines=[]
    for group in groups:
        words=sorted(group,key=lambda g:g.left)
        top,bottom=min(g.top for g in group),max(g.bottom for g in group)
        center=(top+bottom)/2
        nearby=[(abs(y-center),size) for y,size in fonts if abs(y-center)<4]
        size=min(nearby)[1] if nearby else median(g.size for g in group)
        lines.append(GeometryLine(words,top,bottom,size))
    rules=[]
    for drawing in page.get_drawings():
        box=rotate_box(tuple(drawing['rect']),width,height,turn)
        if box[2]-box[0]>=min(width,height)*.4 and box[3]-box[1]<2:
            rules.append((box[0],(box[1]+box[3])/2,box[2]))
    rules=sorted(set((round(a,2),round(b,2),round(c,2)) for a,b,c in rules),key=lambda r:r[1])
    return lines,rules,turn
