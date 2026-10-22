"""Measure complete exact-data tables before using spare page space for type."""
from .text_capacity import wrap_copy


def exact_table_layout(rows: list[tuple[str, ...]], widths: tuple[float, ...],
                       available_height: float, *, enlarge: bool = False
                       ) -> tuple[int, list[tuple[str, ...]], list[float]]:
    """Enlarge only a complete table; otherwise preserve 14 pt pagination.

    Heights include the repeated header. Measure every cell at the candidate
    font size, retaining its complete text. Never enlarge a subset of rows to
    fill a page at the cost of an additional continuation.
    """
    for size in ((18, 16, 14) if enlarge else (14,)):
        scale = size / 14
        wrapped = [tuple('\n'.join(wrap_copy(value, width - .30, size))
                         for value, width in zip(row, widths)) for row in rows]
        heights = [.4 * scale] + [
            max(.4 * scale, max(len(value.splitlines()) for value in row) * .24 * scale + .14)
            for row in wrapped]
        if sum(heights) <= available_height + 1e-6 or size == 14:
            return size, wrapped, heights
