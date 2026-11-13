"""Recognize the explicit absolute-magnitude operator without changing source values."""
import math
import re


def magnitude_comparison(text,start,end,values):
    before=text[:start];after=text[end:]
    if not (re.search(r'\b(?:absolute\s+)?magnitudes?\s*$',before,re.I)
            or re.match(r'\s+(?:in|of)\s+(?:the\s+)?(?:absolute\s+)?magnitudes?\b',after,re.I)):
        return None
    if len(values)<2 or any(value is None or not math.isfinite(value) for value in values):
        return None
    magnitudes=[abs(value) for value in values]
    steps=[b-a for a,b in zip(magnitudes,magnitudes[1:])]
    up=any(value>0 for value in steps);down=any(value<0 for value in steps)
    return dict(state='INCREASED' if magnitudes[-1]>magnitudes[0] else
        'DECREASED' if magnitudes[-1]<magnitudes[0] else 'FLAT',
        start=magnitudes[0],end=magnitudes[-1],increasing_end=steps[-1]>0,
        non_monotonic=dict(is_non_monotonic=up and down,
            had_rebound=any(value<0 and any(later>0 for later in steps[i+1:])
                            for i,value in enumerate(steps)),
            had_intermediate_decline=up and down))
