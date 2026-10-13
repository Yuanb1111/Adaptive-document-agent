"""Bind centered unit superheaders to contiguous numeric columns using geometry."""
import re
from dataclasses import replace
from itertools import combinations

from .borderless_layout import geometric_headers

_UNIT = re.compile(r'\(\s*(units?|%|％|RMB|CNY|USD|HKD|EUR|GBP)\s*\)', re.I)


def grouped_unit_headers(unit_lines, title_lines, anchors):
    """Return labels only for a unique complete partition; never divide by position."""
    if not anchors:
        return None
    _, centers, gap = anchors
    if len(centers) > 24:
        return None
    for line in unit_lines:
        matches = list(_UNIT.finditer(line.text))
        if not 1 < len(matches) <= min(6, len(centers)-1) or _UNIT.sub('', line.text).strip():
            continue
        boxes = [line.bounds(m.start(), m.end()) for m in matches]
        if not all(boxes):
            continue
        positions = [sum(box) / 2 for box in boxes]
        fits = []
        for cuts in combinations(range(1, len(centers)), len(matches)-1):
            edges = (0, *cuts, len(centers))
            errors = [abs(sum(centers[a:b])/(b-a)-x)/gap
                      for (a,b),x in zip(zip(edges,edges[1:]),positions)]
            if max(errors) <= .55:
                fits.append((sum(e*e for e in errors),edges))
        fits.sort()
        if not fits or len(fits)>1 and fits[1][0]-fits[0][0]<.08:
            continue
        group_gap = min(b-a for a,b in zip(positions,positions[1:]))
        titles = geometric_headers([
            replace(line, text=re.sub(r'(?<=\w)\(\d+\)', lambda m:' '*len(m.group()), line.text))
            for line in title_lines if not re.search(r'(?i)first\s*half|second\s*half|months?|year\s*ended',line.text)
        ], (positions,positions,group_gap), ['']*len(matches))
        labels = []
        for (a,b),match,title in zip(zip(fits[0][1],fits[0][1][1:]),matches,titles):
            labels.extend([f'{title} {match.group()}'.strip()]*(b-a))
        return labels
    return None


def qualified_year_periods(year_line, header_lines, periods):
    """An 'of2024' cell needs its own duration heading, not an annual guess."""
    tokens = list(re.finditer(r'\b(?:of\s*)?((?:19|20)\d{2})\b', year_line.text, re.I))
    if len(tokens) != len(periods):
        return periods
    result = list(periods)
    boxes = [year_line.bounds(m.start(),m.end()) for m in tokens]
    gap = min((sum(b)/2-sum(a)/2 for a,b in zip(boxes,boxes[1:]) if a and b),default=0)
    for index, token in enumerate(tokens):
        if not token.group().lower().startswith('of'):
            continue
        result[index] = None
        if not boxes[index] or gap <= 0:
            continue
        labels = set()
        for line in header_lines:
            for match in re.finditer(r'(?i)\b(first|second)\s*half\b',line.text):
                box = line.bounds(match.start(),match.end())
                if box and abs(sum(box)/2-sum(boxes[index])/2) < gap*.4:
                    labels.add(('1H' if match.group(1).lower()=='first' else '2H')+token.group(1))
        if len(labels)==1:
            result[index] = labels.pop()
    return result
