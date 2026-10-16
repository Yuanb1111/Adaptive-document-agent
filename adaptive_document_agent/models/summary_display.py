"""Optional writer-selected structure over exact, independently reviewed copy."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SummaryDisplay(BaseModel):
    model_config = ConfigDict(extra='forbid')
    layout: Literal['paragraphs', 'comparison', 'timeline', 'relationship', 'key_metrics'] = 'paragraphs'
    break_after: list[str] = Field(default_factory=list, max_length=8, description=
        'Exact unique suffixes of complete statements in this item text, in reading order. '
        'They choose visual breaks without rewriting copy or repeating its full text. '
        'Use chronological or relationship layouts only when that relation is explicit in the source.')
