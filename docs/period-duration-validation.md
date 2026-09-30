# Month-duration scope validation

## Confirmed defect

Reproduced on `63c36914fcc29ca47107b79bb0d0ed869ebcf2ee` before editing production code:

```python
from adaptive_document_agent.document_model.period_semantic_validator import (
    are_periods_comparable, extract_period_basis,
)

for count in (3, 6, 9):
    print(extract_period_basis(f"{count} months ended"))
    print(extract_period_basis(f"{count} months ended 30 June 2025"))
print(are_periods_comparable(
    "3 months ended 30 June 2025", "6 months ended 30 June 2025",
))
```

Before: each numeric duration returned `generic` without the date and
`point_in_time` with that date. The comparison returned `(True, '')`.
The same collapse affected 3 versus 9 and 6 versus 9 months. English word
forms for three and six already returned distinct bases, but comparing a
numeric label with its equivalent word form incorrectly rejected it.

The display formatter recognized month counts more broadly than the basis
validator. Downstream comparison, series grouping, chartability, and claim
validation consume the original label, so correct display text did not protect
calculations. A pre-fix test run confirmed six calculation tools allowed mixed
durations and series grouping combined all three durations into one series.

## Fix and scope

- Share the English month-count recognizer between display formatting,
  interim detection, and period-basis extraction
- Resolve an explicit duration before any embedded end date
- Support numeric counts and English number words generically, rather than
  matching company names or the three requested examples only
- Recognize duration even if the year is missing, while preserving the original
  display label and never supplying a missing year
- Preserve balance-sheet/date handling, existing period aliases, source values,
  page evidence, and explicit unaudited markers
- Invalidate cached analysis/session results; extracted table caches are
  unchanged because table extraction is outside this fix

Initial regression run: **27 failed, 16 passed** before the production change.
Expanded targeted suite: **63 passed** after the change.
Run it with:

```bash
python -m pytest tests/test_month_duration_semantics.py -ra
python -m pytest -ra
```

Coverage includes all requested labels, date syntaxes, missing dates, December
end dates, number words 1–12, numeric counts, whitespace/case variants, leading
zeros, malformed tokens, same-duration comparisons, six executor operations,
series/chart/claim guards, and table-observation normalization with retained
raw values and evidence. A minimal public-header transcription is also rendered
into an in-memory PDF and passed through PDF text extraction. Tests are offline
and require no model credentials.

## Real-document validation and known upstream limitation

The public [Apple FY25 Q3 statements](https://www.apple.com/newsroom/pdfs/fy2025-q3/FY25_Q3_Consolidated_Financial_Statements.pdf)
were downloaded to temporary validation storage and parsed through `PDFParser`
and `ObservationExtractor`: 3 pages and 211 observations. No original PDF or
user document is included in this commit.

The public table has separate 3-month and 9-month column groups. Its source
header strings classify correctly when retained. **The full PDF path is not
certified period-safe by this fix:** current upstream table reconstruction loses
those multi-level duration headers and emits bare years for both groups. This
validator cannot recover information already removed by extraction.

The upstream problem also reproduces independently of the public document with
this fully synthetic table (the amounts are invented test data):

```python
from adaptive_document_agent.extraction.table_reconstructor import TableReconstructor

raw = [
    ["Metric", "Three Months Ended", None, "Nine Months Ended", None],
    [None, "June 28", "June 29", "June 28", "June 29"],
    [None, "2025", "2024", "2025", "2024"],
    ["Revenue", "120", "100", "360", "300"],
]
output = TableReconstructor.reconstruct_multi_tier_headers(
    raw, default_unit="currency", default_currency="USD",
    default_scale=1, context="Statement of operations",
)
print(output[1])
# Observed: [None, '2025', '2024', '2025', '2024']
# Needed in a separate fix: preserve each disclosed duration alongside its year.
```

Header propagation needs a separately reproduced, geometry-aware extraction
fix. This PR deliberately does not rewrite that parser or infer missing source
scope. It also does not change the pre-existing policy for wholly unrecognized
periods, infer fiscal-calendar alignment, or certify live LLM extraction.
