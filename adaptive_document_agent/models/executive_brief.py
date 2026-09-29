"""Source-bound editorial summary shared by the Overview tab and PowerPoint."""
from pydantic import BaseModel, ConfigDict, Field


class BriefQuote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: int = Field(ge=1)
    text: str = Field(min_length=8, max_length=1800)


class ExecutiveBriefItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=60)
    text: str = Field(min_length=1, max_length=550)
    evidence: list[BriefQuote] = Field(min_length=1, max_length=4)


class ExecutiveBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="Key takeaways", min_length=1, max_length=100)
    items: list[ExecutiveBriefItem] = Field(min_length=1, max_length=7)
