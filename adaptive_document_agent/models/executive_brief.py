"""Source-bound editorial summary shared by the Overview tab and PowerPoint."""
from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Literal


class BriefQuote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: int = Field(ge=1)
    text: str = Field(min_length=8, max_length=1800)


class BriefQuantityRepresentation(BaseModel):
    """Model-declared magnitude wording bound to one signed quoted quantity."""
    model_config = ConfigDict(extra="forbid")
    quantity_text: str = Field(min_length=1, max_length=100)
    source_value: str = Field(min_length=1, max_length=60)
    representation: Literal["absolute_magnitude"]


class BriefComparisonTable(BaseModel):
    """Model-selected source comparisons, with no executable expressions."""
    model_config = ConfigDict(extra="forbid")
    headers: list[str] = Field(min_length=2, max_length=4)
    rows: list[list[str]] = Field(min_length=1, max_length=8)

    @model_validator(mode='after')
    def rectangular(self):
        if any(len(row) != len(self.headers) for row in self.rows):
            raise ValueError('Brief comparison tables must be rectangular.')
        if any(not cell.strip() or len(cell) > 180 for row in [self.headers, *self.rows] for cell in row):
            raise ValueError('Brief table cells must be nonempty and at most 180 characters.')
        return self


class ExecutiveBriefItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=60)
    text: str = Field(min_length=1, max_length=550)
    evidence: list[BriefQuote] = Field(min_length=1, max_length=4)
    quantity_representations: list[BriefQuantityRepresentation] = Field(default_factory=list, max_length=20)
    comparison_table: BriefComparisonTable | None = None


def brief_claim_text(item: ExecutiveBriefItem, *, include_label: bool = True,
                     canonicalize_table_signs: bool = False) -> str:
    table = item.comparison_table
    cells = [cell for row in [table.headers, *table.rows] for cell in row] if table else []
    if canonicalize_table_signs:
        import re
        # A complete literal accounting cell has an explicit negative sign.
        # This validation view never rewrites source/display cells or prose.
        cells = ['-' + cell.strip()[1:-1].strip()
                 if re.fullmatch(r'\s*\(\s*\d[\d,. ]*\s*\)\s*', cell) else cell for cell in cells]
    return '. '.join([*([item.label] if include_label else []), item.text, *cells])


class ExecutiveBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="Key takeaways", min_length=1, max_length=100)
    items: list[ExecutiveBriefItem] = Field(min_length=1, max_length=7)
