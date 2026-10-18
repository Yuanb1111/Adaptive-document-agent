"""Literal complete grids from independent ruling and decoded word geometry.

This inventory is independent of analytical row selection. It retains headings,
blank subtotals, wrapped labels, notes and rotated page provenance.
"""
import re
from statistics import median

from adaptive_document_agent.models.table import ExtractedTable
from adaptive_document_agent.utils.ids import stable_id
from .source_geometry import page_geometry, rotate_box

_VALUE=re.compile(r'^(?:(?=[-+\d,.()%/]*\d)[-+\d,.()%/]+|N/A|Nil|[—–-])$')


def value_words(line,left):
    for index,word in enumerate(line.words):
        prior=line.words[index-1] if index else None
        if (_VALUE.fullmatch(word.text) and word.left>left+20
                and (prior is None or word.left-prior.right>8)):
            return [w for w in line.words[index:] if _VALUE.fullmatch(w.text)]
    return []


def _prose(line,left):
    if value_words(line,left):
        return False
    gaps=[b.left-a.right for a,b in zip(line.words,line.words[1:])]
    return len(line.text)>85 and max(gaps,default=0)<12


def table_regions(lines,rules,height):
    """Join adjacent ruled bands only while no intervening body prose exists."""
    bands=[]
    for index,(left,top,right) in enumerate(rules):
        bottom=rules[index+1][1] if index+1<len(rules) else height-42
        content=[l for l in lines if top-.5<=l.top and l.bottom<=bottom+.5
                 and l.words and l.words[0].left>=left-2 and l.words[-1].right<=right+3]
        if not content or any(_prose(l,left) for l in content):
            continue
        if any(re.match(r'(?i)^notes?\s*[:：]',l.text) for l in content):
            continue  # Annotations after a closing rule are outside the grid.
        numeric=[l for l in content if value_words(l,left)]
        has_data=any(any(w.left<min(v.left for v in value_words(l,left))-8 for w in l.words)
                     for l in numeric)
        has_data=has_data or any(len(value_words(l,left))>=2 and not _year_header(value_words(l,left))
                                for l in numeric)
        if (not has_data and any(l.words[0].left<left+18 and len(l.text)>6 for l in content)):
            continue  # A separate left-aligned caption between closed tables.
        bands.append((left,top,right,bottom,content,has_data))
    groups=[]
    for band in bands:
        if (groups and abs(groups[-1][-1][3]-band[1])<1
                and min(groups[-1][-1][2],band[2])-max(groups[-1][-1][0],band[0])>40):
            groups[-1].append(band)
        else:
            groups.append([band])
    return [(min(b[0] for b in g),g[0][1],max(b[2] for b in g),g[-1][3],
             [l for b in g for l in b[4]]) for g in groups if any(b[5] for b in g)]


def _anchors(lines,left):
    records=[(line,value_words(line,left)) for line in lines]
    # Header years without a left-hand label do not establish a body row.
    labelled=[(line,values) for line,values in records if values and _row_label(line,values,left)]
    if not labelled:
        labelled=[(line,values) for line,values in records if len(values)>=2 and not _year_header(values)]
        if not labelled:
            return []
    count=max(len(values) for _,values in labelled)
    full=[values for _,values in labelled if len(values)==count]
    result=[]
    for column in range(count):
        values=[row[column] for row in full]
        starts,ends=[v.left for v in values],[v.right for v in values]
        align='right' if max(ends)-min(ends)<=max(starts)-min(starts) else 'left'
        result.append((median(starts),median(ends),align))
    return result


def _column(word,anchors):
    data_left=min(a for a,b,_ in anchors)
    if word.right<data_left-5:
        return 0
    return 1+min(range(len(anchors)),key=lambda i:abs(
        (word.right if anchors[i][2]=='right' else word.left)-
        (anchors[i][1] if anchors[i][2]=='right' else anchors[i][0])))


def _row_label(line,values,left):
    return (any(w.right<values[0].left-8 for w in line.words)
            and line.words[0].left<left+max(20,(values[0].left-left)*.5))


def _year_header(values):
    return all(re.fullmatch(r'(?:19|20)\d{2}',v.text) for v in values)


def _header(line,anchors,guides,left,right):
    groups=[]
    for word in line.words:
        if not groups or word.left-groups[-1][-1].right>7:
            groups.append([])
        groups[-1].append(word)
    centers=[(a+b)/2 for a,b,_ in anchors]
    label_boundary=(anchors[0][0]-(anchors[1][0]-anchors[0][0])*.55 if len(anchors)>1
                    else (left+anchors[0][0])/2)
    row=['']*(len(anchors)+1)
    spans=[]
    for group in groups:
        start,end=group[0].left,group[-1].right
        text=' '.join(w.text for w in group)
        center=(start+end)/2
        candidates=[(y-line.bottom,a,b) for a,y,b in guides if
                    -1<=y-line.bottom<38 and a-2<=center<=b+2 and b-a<(right-left)*.9]
        covered=[]
        if candidates:
            _,a,b=min(candidates)
            covered=[c+1 for c,x in enumerate(centers) if a-2<=x<=b+2]
        if len(covered)>1:
            column=covered[0]
            spans.append((column,covered[-1]))
            row[column]+=(' ' if row[column] else '')+text
        else:
            # Narrow adjacent headings may be separated by less than a word
            # gap. Use their body-column alignment, not the phrase's center.
            for word in group:
                column=0 if word.right<label_boundary else 1+min(range(len(anchors)),
                    key=lambda c:abs((word.right if anchors[c][2]=='right' else (word.left+word.right)/2)-
                                     (anchors[c][1] if anchors[c][2]=='right' else centers[c])))
                row[column]+=(' ' if row[column] else '')+word.text
    return row,spans


def _body_start(lines, anchors, left):
    from .record_table_headers import reporting_period_row
    body_start=next((i for i,l in enumerate(lines) if value_words(l,left)
                     and _row_label(l,value_words(l,left),left)
                     and not reporting_period_row([l.text])),len(lines))
    if body_start==len(lines):
        body_start=next((i for i,l in enumerate(lines) if len(value_words(l,left))==len(anchors)
                         and not _year_header(value_words(l,left))
                         and not reporting_period_row([l.text])),len(lines))
    # Keep wrapped first labels/section headers as body, never column headings.
    while (body_start and not reporting_period_row([lines[body_start-1].text])
           and max(w.right for w in lines[body_start-1].words)<min(a for a,b,_ in anchors)-5):
        body_start-=1
    return body_start


def _split_repeated_headers(region):
    """Separate source grids when a later block repeats its column headings.

    A page border can enclose several independent tables. Joining their rows
    would make the first period and unit declarations govern later blocks.
    Require multiple ordered literal header matches before a new data row;
    ordinary row labels or a lone date cannot establish a new table.
    """
    left,top,right,bottom,lines=region
    anchors=_anchors(lines,left)
    if not anchors:
        return [region]
    first=_body_start(lines,anchors,left)
    signature=lambda line: ' '.join(line.text.casefold().split())
    headers=[signature(line) for line in lines[:first]]
    cuts=[]
    index=first+1
    while index<len(lines):
        line_key=signature(lines[index])
        matches=[i for i,key in enumerate(headers) if key==line_key and re.search(r'[a-zA-Z\u3400-\u9fff]',key)]
        if not matches:
            index+=1
            continue
        following=next((i for i in range(index+1,min(len(lines),index+len(headers)+3))
                        if value_words(lines[i],left) and _row_label(lines[i],value_words(lines[i],left),left)),None)
        if following is None:
            index+=1
            continue
        matched=[]
        cursor=matches[0]
        for line in lines[index:following]:
            key=signature(line)
            position=next((i for i in range(cursor,len(headers)) if headers[i]==key),None)
            if position is not None:
                matched.append(key)
                cursor=position+1
        if len(set(matched))>=2:
            # A reporting-date caption can precede the repeated field names.
            # Keep it with the new block instead of leaving its year among the
            # previous block's numeric cells. Only adjacent complete date
            # declarations qualify, including wrapped source lines.
            from .record_table_headers import reporting_period_row
            start=index
            lower=cuts[-1]+1 if cuts else first+1
            for count in range(1,min(3,index-lower)+1):
                prefix=lines[index-count:index]
                sequence=[*prefix,lines[index]]
                if (all(0<=b.top-a.bottom<=35 for a,b in zip(sequence,sequence[1:]))
                        and reporting_period_row([line.text for line in prefix])):
                    start=index-count
            cuts.append(start)
            index=following+1
        else:
            index+=1
    bounds=[0,*cuts,len(lines)]
    return [(left,top if start==0 else lines[start].top,right,
             bottom if end==len(lines) else lines[end].top,lines[start:end])
            for start,end in zip(bounds,bounds[1:])]


def _grid(lines,left,right,guides):
    anchors=_anchors(lines,left)
    if not anchors:
        return [],[],[]
    width=len(anchors)+1
    body_start=_body_start(lines,anchors,left)
    headers,body,spans=[],[],[]
    for index,line in enumerate(lines):
        if index<body_start:
            row,merges=_header(line,anchors,guides,left,right)
            headers.append(row)
            spans.extend((index,a,b) for a,b in merges)
            continue
        cells=[[] for _ in range(width)]
        for word in line.words:
            column=_column(word,anchors)
            cells[column].append(word.text)
        row=[' '.join(c) for c in cells]
        body.append((row,line))
    merged=[]
    for i,(row,line) in enumerate(body):
        values=any(row[1:])
        if merged and not values and row[0] and not row[0].endswith(':'):
            prior,previous=merged[-1]
            # A preceding label-only line and the numeric continuation share
            # a hanging indent. Preserve section titles/colon parents separately.
            if not any(prior[1:]) and abs(previous.size-line.size)<2 and line.top-previous.bottom<10:
                prior[0]+=' '+row[0]
                previous.bottom=line.bottom
                continue
        if merged and values:
            prior,previous=merged[-1]
            if (not any(prior[1:]) and prior[0] and not prior[0].endswith(':')
                    and line.top-previous.bottom<10 and row[0]
                    and line.words[0].left>previous.words[0].left+2):
                row[0]=prior[0]+' '+row[0]
                merged.pop()
        # Wrapped text in a value-only qualitative column belongs to its prior
        # row (e.g. the remainder of a useful-life sentence).
        if merged and not row[0] and any(row[1:]) and not value_words(line,left):
            prior,previous=merged[-1]
            if line.top-previous.bottom<10:
                for column,text in enumerate(row):
                    if text:
                        prior[column]+=(' ' if prior[column] else '')+text
                continue
        merged.append((row,line))
    return headers,[row for row,_ in merged],spans


def _notes(lines,tables):
    """Numbered and unnumbered small-print notes, with exact continuation text."""
    for index,table in enumerate(tables):
        bottom=table.reading_bbox[3]
        limit=tables[index+1].reading_bbox[1] if index+1<len(tables) else float('inf')
        eligible=[l for l in lines if bottom<l.top<limit]
        collecting=False
        note_size=0
        paragraph=[]
        for line in eligible:
            marker=re.match(r'(?i)^(?:notes?\s*[:：]|\(\d+\))',line.text)
            if marker:
                if paragraph:
                    table.raw_footnotes.append('\n'.join(paragraph))
                paragraph=[line.text]
                collecting=True
                note_size=line.size
            elif collecting and line.size<=note_size+.7 and not re.fullmatch(r'[–—-]\s*\d+\s*[–—-]',line.text):
                paragraph.append(line.text)
            elif collecting:
                break
        if paragraph:
            table.raw_footnotes.append('\n'.join(paragraph))


def extract_ruled_source_tables(textpage,page,page_number):
    lines,rules,rotation=page_geometry(textpage,page)
    height=page.rect.width if rotation in (90,270) else page.rect.height
    regions=[part for region in table_regions(lines,rules,height)
             for part in _split_repeated_headers(region)]
    guides=[]
    for drawing in page.get_drawings():
        box=rotate_box(tuple(drawing['rect']),page.rect.width,page.rect.height,rotation)
        if box[2]-box[0]>12 and box[3]-box[1]<2:
            guides.append((box[0],(box[1]+box[3])/2,box[2]))
    tables=[]
    for left,top,right,bottom,content in regions:
        headers,rows,spans=_grid(content,left,right,guides)
        if not rows:
            continue
        reading_bbox=(left,top,right,bottom)
        reading_width=page.rect.height if rotation in (90,270) else page.rect.width
        bbox=rotate_box(reading_bbox,reading_width,height,(-rotation)%360)
        table=ExtractedTable(table_id=stable_id('ruled_source',page_number,reading_bbox),page=page_number,
            raw_cells=rows,raw_header_cells=headers,raw_header_lines=[l.text for l in content[:len(headers)]],
            raw_header_spans=spans,
            raw_body_lines=[l.text for l in content[len(headers):]],bbox=bbox,confidence=.9,
            reading_bbox=reading_bbox,source_rotation=rotation,source_layout_status='checked')
        table.raw_context_lines=[l.text for i,l in enumerate(lines) if 0<top-l.bottom<25
            and l.words[0].left<left+15 and len(l.text)<100 and not _prose(l,left)
            and not (i and 0<l.top-lines[i-1].bottom<8 and abs(l.size-lines[i-1].size)<.7
                     and _prose(lines[i-1],left))]
        tables.append(table)
    _notes(lines,tables)
    # A ruled grid is not permission to discard a separate unruled grid on
    # the same page. Leave potentially aligned outside data to the fallback.
    outside=[l for l in lines if len(value_words(l,0))>=2
             and not _year_header(value_words(l,0))
             and not re.match(r'(?i)^(?:notes?\s*[:：]|\(\d+\))',l.text)
             and not any(t.reading_bbox[1]-.5<=l.top<=t.reading_bbox[3]+.5 for t in tables)]
    from .source_table_audit import table_digest
    return tables,{'method':'independent_decoded_ruling_geometry','status':'checked',
                   'rotation':rotation,'table_ids':[t.table_id for t in tables],
                   'table_digests':{t.table_id:table_digest(t) for t in tables},
                   'outside_aligned_rows':len(outside) if len(outside)>=2 else 0,
                   'region_count':len(regions),'unresolved_regions':len(regions)-len(tables)}
