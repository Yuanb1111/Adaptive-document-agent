"""Copy an explicit table description without inferring a metric's meaning."""

import re
from collections.abc import Sequence

from adaptive_document_agent.models import Observation, ParsedDocument


_DESCRIPTION_START = re.compile(
    r"(?i)\b(?:the following table|the table below|this table)\s+"
    r"(?:sets forth|sets out|shows|presents|provides|summari[sz]es|details|lists|reports)\b"
)
_ABBREVIATIONS = {"e.g", "i.e", "mr", "mrs", "ms", "dr", "prof", "st", "vs", "approx", "no", "fig", "eq", "inc"}


def source_table_context(series: Sequence[Observation], document: ParsedDocument) -> str:
    """Return one complete, short source sentence for the series' shared table.

    Table/page evidence, rather than a nearby heading or cached semantic label,
    binds the description. Source text remains untrusted display text. Missing
    or ambiguous evidence and descriptions produce no caption.
    """
    if not series:
        return ""
    common = None
    for observation in series:
        locations = {(evidence.page, evidence.table_id) for evidence in observation.evidence
                     if evidence.table_id}
        if not locations:
            return ""
        common = locations if common is None else common & locations
    if len(common) != 1:
        return ""
    page_number, table_id = next(iter(common))
    tables = [table for page in document.pages if page.page_number == page_number
              for table in page.tables if table.table_id == table_id and table.page == page_number]
    if len(tables) != 1:
        return ""
    text = " ".join(" ".join(tables[0].raw_header_lines).split())
    descriptions = list(_DESCRIPTION_START.finditer(text))
    if len(descriptions) != 1:
        return ""
    remainder = text[descriptions[0].start():]
    for end in re.finditer(r"[.!?](?=\s|$)", remainder):
        candidate = remainder[:end.end()]
        if len(candidate) > 250:
            return ""  # Preserve the whole source sentence or omit it.
        if end.group() == ".":
            last_word = candidate[:-1].rsplit(" ", 1)[-1].casefold()
            if last_word in _ABBREVIATIONS or re.fullmatch(r"(?:[a-z]\.)*[a-z]", last_word):
                continue
        return candidate
    return ""
