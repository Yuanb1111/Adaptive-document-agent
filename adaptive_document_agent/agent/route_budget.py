"""Budget arithmetic over model-ranked evidence ranges; no semantic selection."""

from typing import Annotated

from pydantic import BaseModel, Field, StrictInt

from adaptive_document_agent.models import AnalysisPageRange

DEEP_ANALYSIS_PAGE_BUDGET = 160


class RouteRangeRefinement(BaseModel):
    range_index: StrictInt = Field(ge=0)
    start_page: StrictInt = Field(ge=1)
    end_page: StrictInt = Field(ge=1)
    reason: str = Field(min_length=1, max_length=600)


class RouteBudgetSelection(BaseModel):
    """Priority order plus optional model-selected, complete evidence subranges."""

    primary_range_indexes: list[Annotated[StrictInt, Field(ge=0)]] = Field(min_length=1, max_length=12)
    refined_ranges: list[RouteRangeRefinement] = Field(default_factory=list, max_length=12)


def covered_pages(ranges: list[AnalysisPageRange]) -> set[int]:
    return {page for item in ranges for page in range(item.start_page, item.end_page + 1)}


def contiguous_spans(pages: set[int]) -> list[tuple[int, int]]:
    """Read each selected page once without filling gaps between ranges."""
    spans: list[tuple[int, int]] = []
    for page in sorted(pages):
        if spans and page == spans[-1][1] + 1:
            spans[-1] = (spans[-1][0], page)
        else:
            spans.append((page, page))
    return spans


def ranked_ranges(selection: RouteBudgetSelection,
                  candidates: list[AnalysisPageRange]) -> list[AnalysisPageRange]:
    indices = selection.primary_range_indexes
    if (not indices or len(indices) != len(set(indices))
            or any(type(index) is not int or index < 0 or index >= len(candidates) for index in indices)):
        raise ValueError("Select distinct, valid candidate range indexes.")
    refinements: dict[int, list[AnalysisPageRange]] = {}
    for subrange in selection.refined_ranges:
        if subrange.range_index not in indices:
            raise ValueError("A refined range must belong to a selected candidate.")
        parent = candidates[subrange.range_index]
        if not parent.start_page <= subrange.start_page <= subrange.end_page <= parent.end_page:
            raise ValueError("A refined range must stay inside its original evidence range.")
        refinements.setdefault(subrange.range_index, []).append(parent.model_copy(update={
            "start_page": subrange.start_page, "end_page": subrange.end_page,
            "reason": (parent.reason + f" Model-selected evidence subrange of pages "
                       f"{parent.start_page}-{parent.end_page}: {subrange.reason}"),
        }))
    return [item for index in indices for item in refinements.get(index, [candidates[index]])]


def fit_ranked_ranges(ranges: list[AnalysisPageRange]) -> list[AnalysisPageRange]:
    """Pack whole ranges in the model's priority order, counting overlap once."""
    if not ranges:
        raise ValueError("A nonempty primary evidence selection is required.")
    if any(item.end_page - item.start_page + 1 > DEEP_ANALYSIS_PAGE_BUDGET for item in ranges):
        raise ValueError("An oversized primary range needs model-selected evidence subranges.")
    selected, pages = [], set()
    for item in ranges:
        combined = pages | covered_pages([item])
        if len(combined) <= DEEP_ANALYSIS_PAGE_BUDGET:
            selected.append(item)
            pages = combined
    if not selected:
        raise ValueError("No complete primary evidence range fits the page budget.")
    if len(selected) < len(ranges):
        note = (f" Deep analysis covers {len(pages)} unique pages within the "
                f"{DEEP_ANALYSIS_PAGE_BUDGET}-page budget; lower-priority ranges that "
                "do not fit remain outside this deep-analysis scope.")
        selected = [item.model_copy(update={"reason": item.reason + note}) for item in selected]
    return sorted(selected, key=lambda item: item.start_page)
