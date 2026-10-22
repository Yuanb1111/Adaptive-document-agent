"""Chart space follows caption length; exact-data pagination preserves groups."""
import pytest

from adaptive_document_agent.services.composition_pagination import table_row_cut
from adaptive_document_agent.services.slide_compositor import compose_geometry


def test_single_chart_short_caption_uses_full_width_without_overlap():
    short = compose_geometry(12.6, 7.09, 1.5, 1, layout='single', has_support=False,
        has_commentary=True, commentary_text='Reported output, FY2021 to FY2023.')
    long = compose_geometry(12.6, 7.09, 1.5, 1, layout='single', has_support=False,
        has_commentary=True, commentary_text='Complete source qualification and interpretation. ' * 20)
    assert short.charts[0].w == pytest.approx(11.5)
    assert short.charts[0].w > long.charts[0].w * 1.5
    assert short.charts[0].h > 3
    assert short.commentary.y > short.charts[0].y + short.charts[0].h
    assert long.commentary.x > long.charts[0].x + long.charts[0].w


def test_support_retains_side_column_even_with_short_caption():
    geometry = compose_geometry(12.6, 7.09, 1.5, 1, layout='single', has_support=True,
        has_commentary=True, commentary_text='Reported output.')
    assert geometry.support.x > geometry.charts[0].x + geometry.charts[0].w
    assert geometry.commentary.y > geometry.support.y + geometry.support.h


@pytest.mark.parametrize('heights,capacity,groups,narrow,expected', [
    ([.4] * 5, 1.3, [5], True, 0),  # Whole comparison moves to wider page.
    ([.4] * 6, 1.7, [2, 4], True, 2),  # Do not peel off two periods.
    ([.4] * 10, 3.2, [1] * 10, False, 5),  # Avoid an eight/two split.
    ([.4] * 10, 3.2, [6, 4], False, 6),  # Preserve groups over exact balance.
    ([.4] * 20, 2.0, [20], False, 5),  # Oversized groups still progress.
    ([.4] * 4, 1.6, [4], False, 4),
])
def test_table_page_breaks(heights, capacity, groups, narrow, expected):
    assert table_row_cut(heights, capacity, groups, narrow=narrow) == expected


def test_variable_height_pagination_preserves_every_row_in_order():
    heights = [.4, .8, .4, 1.2, .4, .4, .8, .4, .4]
    remaining = list(enumerate(heights))
    pages = []
    while remaining:
        cut = table_row_cut([h for _, h in remaining], 2.4, [1] * len(remaining))
        assert cut > 0
        pages.append(remaining[:cut])
        remaining = remaining[cut:]
    assert [i for page in pages for i, _ in page] == list(range(len(heights)))
    assert all(sum(h for _, h in page) <= 2.4 + 1e-6 for page in pages)


def test_native_table_continuations_are_balanced_and_keep_every_fact():
    from adaptive_document_agent.document_model import DocumentIndex
    from adaptive_document_agent.models import PresentationSlide, PresentationVisualBlock
    from adaptive_document_agent.services.slide_compositor import render_composed_slide, validate_composed_geometry
    from tests.test_p0_composition import observation, result_for
    from tests.test_presentation_brief import blank_deck
    records = [observation(f'fact-{i:02}', f'Measure {i:02}', i + 10, None) for i in range(13)]
    plan = PresentationSlide(id='table', slide_type='analysis', title='Reported measurements',
        layout='data_overview', source_pages=[3], visual_blocks=[
            PresentationVisualBlock(role='table', observation_ids=[o.id for o in records])])
    result = result_for(records, [], plan)
    before = result.model_dump_json()
    deck = blank_deck()
    pages = render_composed_slide(deck, plan, [], result, DocumentIndex(records))
    tables = [s for page in pages for s in page.shapes if s.has_table]
    assert len(pages) == len(tables) == 2
    assert sorted(len(s.table.rows) - 1 for s in tables) == [6, 7]
    assert [oid for s in tables for oid in s.name.removeprefix('table:').split(',')] == [o.id for o in records]
    assert all(s.table.cell(0, 0).text == 'Metric' for s in tables)
    assert all(s.table.cell(r, 1).text == 'Unspecified' for s in tables for r in range(1, len(s.table.rows)))
    assert result.model_dump_json() == before
    validate_composed_geometry(deck)
