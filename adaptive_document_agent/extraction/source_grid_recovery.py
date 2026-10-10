"""Recover literal aligned source grids without assigning analytical meaning.

Independent repeated cell boundaries support qualitative and scenario tables.
No years, financial keywords, currency guesses or document types are required.
"""
import re
from statistics import median

from adaptive_document_agent.models.table import ExtractedTable
from adaptive_document_agent.utils.ids import stable_id
from .borderless_layout import source_lines


def _cells(line, gap=12):
    groups = []
    for span in line.spans:
        if not groups or span[2] - groups[-1][-1][3] >= gap:
            groups.append([])
        groups[-1].append(span)
    return [(line.text[g[0][0]:g[-1][1]], g[0][2], g[-1][3]) for g in groups]


def recover_source_grids(page, page_number, existing, *, words=None):
    lines = source_lines(page, '', str, words=words)
    candidates = []
    for i, line in enumerate(lines):
        cells = _cells(line)
        if len(cells) >= 2 and len(cells[0][0]) <= 110 and not cells[0][0].rstrip().endswith(':'):
            candidates.append((i, cells))
    runs = []
    for item in candidates:
        i, cells = item
        if runs:
            j, prior = runs[-1][-1]
            # Permit a single close wrapped row label between data rows.
            between = lines[j+1:i]
            compatible = (i-j <= 2 and len(cells) == len(prior)
                and all(abs(a[1]-b[1]) <= 3 or abs(a[2]-b[2]) <= 3
                        for a,b in zip(cells,prior))
                and all(l.spans and max(s[3] for s in l.spans) < cells[1][1]
                        and l.top-lines[j].bottom < 20 for l in between))
            if compatible:
                runs[-1].append(item)
                continue
        runs.append([item])
    tables = []
    for run in runs:
        if len(run) < 3:
            continue
        first, last = run[0][0], run[-1][0]
        bbox = (min(c[1] for _,row in run for c in row), lines[first].top,
                max(c[2] for _,row in run for c in row), lines[last].bottom)
        if any(t.bbox and min(bbox[2],t.bbox[2]) > max(bbox[0],t.bbox[0])
               and min(bbox[3],t.bbox[3]) > max(bbox[1],t.bbox[1]) for t in existing):
            continue
        width = len(run[0][1])
        if width > 2 and not any(re.search(r'\d',c[0]) for _,row in run for c in row[1:]):
            continue  # repeated multi-line column headings are not a new table
        # Wide prose columns are only accepted with a stable second boundary
        # and short labels. An ordinary justified paragraph has no such grid.
        starts = [median(row[c][1] for _,row in run) for c in range(width)]
        if any(max(row[c][1] for _,row in run)-min(row[c][1] for _,row in run) > 8
               and max(row[c][2] for _,row in run)-min(row[c][2] for _,row in run) > 3
               for c in range(1,width)):
            continue
        body = []
        previous = first-1
        for i, row in run:
            cells = [re.sub(r'(?<=\s)(?:\.\s*){2,}', ' ', c[0]).strip() for c in row]
            prefix = lines[i-1] if i else None
            if (prefix and i-1 >= previous and prefix.spans
                    and max(s[3] for s in prefix.spans) < starts[1]
                    and 0 <= lines[i].top-prefix.bottom <= 8
                    and 0 < row[0][1]-min(s[2] for s in prefix.spans) < 20):
                cells[0] = prefix.text + ' ' + cells[0]
            body.append(cells)
            previous = i+1
        headers, header_lines = [[] for _ in range(width)], []
        centers = [median((row[c][1]+row[c][2])/2 for _,row in run) for c in range(width)]
        header_left = (centers[1]-(centers[2]-centers[1])*.5 if width > 2 else starts[1]-12)
        # Only geometrically aligned tiers, stopping at full-width prose.
        for line in reversed(lines[max(0,first-24):first]):
            if not line.spans:
                break
            if max(s[3] for s in line.spans) < starts[1]:
                continue  # first row's wrapped label, not a column heading
            if min(s[2] for s in line.spans) < header_left:
                break
            header_lines.insert(0,line.text)
            for value,left,right in _cells(line, gap=8):
                center = (left+right)/2
                covered = [c for c in range(1,width) if left-3 <= centers[c] <= right+3]
                if not covered:
                    for c in range(1,width-1):
                        if abs(center-(centers[c]+centers[c+1])/2) <= (centers[c+1]-centers[c])*.08:
                            covered = [c,c+1]
                            break
                for c in covered or [min(range(1,width),key=lambda c:abs(centers[c]-center))]:
                    headers[c].insert(0,value)
        table = ExtractedTable(table_id=stable_id('source_grid',page_number,bbox), page=page_number,
            raw_cells=body, raw_header_cells=[[' '.join(col) for col in headers]] if header_lines else [],
            raw_header_lines=header_lines, raw_body_lines=[l.text for l in lines[first:last+1]],
            bbox=bbox, confidence=.65,
            warnings=['Literal aligned source grid; analytical column meaning is unresolved.'])
        # Numeric row labels can make the older parser mistake leading data
        # for header context. Restore those evidenced rows to the same physical
        # fragment instead of exporting a disconnected second table.
        owner = next((t for t in existing if t.raw_header_lines and t.raw_cells
            and max(map(len,t.raw_cells)) == width
            and all(line in t.raw_header_lines for line in table.raw_body_lines)
            and t.bbox and bbox[3] <= t.bbox[1] and t.bbox[1]-bbox[3] < 40),None)
        if owner is not None:
            owner.raw_cells = body + owner.raw_cells
            owner.raw_header_lines = owner.raw_header_lines[:owner.raw_header_lines.index(table.raw_body_lines[0])]
            owner.raw_body_lines = table.raw_body_lines + owner.raw_body_lines
            owner.bbox = (min(bbox[0],owner.bbox[0]),bbox[1],max(bbox[2],owner.bbox[2]),owner.bbox[3])
            continue
        tables.append(table)
    return tables
