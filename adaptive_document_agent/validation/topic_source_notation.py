"""Recognize source-bound period shorthand and page locators, not amounts."""
import re

from .presentation_plan_validator import PresentationPlanValidator


def without_topic_source_notation(text, observations):
    """Normalize only the numeric-check copy; semantic review sees original prose.

    A duration must occur in selected source periods and explicit temporal
    syntax. Bare magnitudes and money remain quantities. Page locators must
    name an owned evidence page; a page number never authorizes an amount.
    """
    pages = {e.page for item in observations for e in item.evidence}
    page_pattern = re.compile(r'\b(?:page|p\.)\s*(\d+)\b(?!\.\d|\s*[-–,]\s*\d)', re.I)

    def page(match):
        if int(match[1]) not in pages:
            raise ValueError('Topic cites a page outside its selected source evidence: ' + match[1])
        return 'source page'

    text = page_pattern.sub(page, text)
    durations = {match[1].upper() for item in observations
                 if (match := re.fullmatch(r'((?:1[0-2]|[1-9])M)(?:19|20)\d{2}', item.period or '', re.I))}
    money = PresentationPlanValidator._money_spans(text)
    has_share = any(item.unit == 'percent' or item.unit_family == 'percentage' for item in observations)
    pattern = re.compile(r'(?<![\w.+−-])(?:1[0-2]|[1-9])M\b', re.I)

    def duration(match):
        if match[0].upper() not in durations or any(a <= match.start() < b for a, b in money):
            return match[0]
        before, after = text[:match.start()], text[match.end():]
        if (re.search(r'(?:[+−-]|人民币|美元|港元|欧元)\s*$', before)
                or re.match(r'\s*(?:人民币|美元|港元|欧元|元)', after)):
            return match[0]
        coordinated = (re.search(r'\b(?:annual|yearly|FY)\s+and\s*$', before, re.I)
                       and re.match(r'\s+(?:[a-z-]+\s+){0,2}(?:periods?|views?)\b', after, re.I))
        temporal = re.match(r'\s+(?:comparison|periods?|views?)\b', after, re.I)
        share = has_share and re.match(r'\s+share\b', after, re.I)
        return 'interim' if coordinated or temporal or share else match[0]

    return pattern.sub(duration, text)
