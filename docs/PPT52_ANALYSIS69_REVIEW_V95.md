# PPT52 / analysis69 content and latency changes (v95)

The saved v94 run recorded 552.6 seconds for analysis and 21.4 seconds for
export, or 573.9 seconds in total. This agrees with the user's approximately
ten-minute upload-to-download measurement. The brief stage took 147.9 seconds;
candidate generation/scoring took 102.6 seconds and reporting 161.1 seconds.
These measurements describe the original run, not a predicted v95 completion time.

## Content failures and corrections

- The original six-item brief was discarded. Validation now accepts five of
  its unchanged findings: concatenated PDF header metadata is located in actual
  source text to recover spacing, independent complete table rows are checked
  separately from ambiguous shared totals, and an explicit year row cannot
  become a percentage merely because the next line contains a percent header.
  Currency, scale, sign, dates, ordered row cells and full unit denominators
  remain source-bound; unsupported metadata still fails closed.
- A shortened patch that cites a subset of the same valid original passages
  retains those passages, including qualifications. A patch selecting different
  evidence is still permitted. The cash-runway patch must retain the financing
  buffer as well as all scenario outcomes; missing-outcome errors now name the
  exact values and units. There is still only one model patch attempt.
- Bare duration table cells can display an explicit header unit only when the
  entire extended phrase occurs in the item's continuous literal quotations.
  This restores a split `60.5 months` phrase without modifying raw model cells
  or inferring an absent unit. Web and slide display use the same adapter.
- The coverage review previously exhausted three calls and rolled back all
  progress. Its production budget now supports eight complete batches plus two
  bounded repair calls. Failed or incomplete transactions still roll back and
  retain the unresolved warning. The model must assess newer comparable views
  and qualifying constraints while retaining accepted observations; no metric
  list or document-type workflow is imposed.
- Compact summary spacing allows complete findings near the template's page
  boundary to share fewer pages at 14–16 pt. Text, order, source pages and notes
  remain intact. Existing sparse-page folding and review-status handling remain.

## Latency work and measured limits

- Percentage and table-cell parsing now memoize identical strings within each
  validation call and skip evidence on pages outside the item's quotations.
  Header lookup is also cached within that call. No document data enters a
  process-wide cache. The original brief classification measured 24.2 seconds
  under cProfile; the final classification measured 3.4 seconds while the full
  test suite was also running (about 86% less). An unprofiled replay measured
  0.7 seconds. These are local validation timings, not pipeline timings.
- Candidate scoring factors identical common fields and interns exact repeated
  observation IDs. Every candidate ID, ordered observation membership (including
  duplicates), source reason and exception can be restored exactly. For the
  actual 160-candidate analysis69 scoring input, the data payload decreased
  from 185,471 to 168,437 characters (9.2%), excluding prompt/schema overhead.
  Smaller inputs are kept literal whenever encoding would add overhead.
- Coverage batching uses a binary search for the largest fitting prefix rather
  than repeatedly encoding every growing prefix. All reported points remain
  present; the request and output limits are unchanged.
- More complete coverage may require additional model calls. Semantic reasoning
  policy is preserved. Input reduction and local validation improvements do not
  establish a new upload-to-download time; a fresh live run must measure it.

## Offline verification

Replay of the saved response directly restores five verified original items.
An explicitly authored offline repair fixture shortened the sixth item and
retained its source-disclosed 12-month financing buffer. It was passed through
the ordinary single-patch merge and full evidence validator, preserving all five
locks. This fixture is not a new provider response or a live latency measurement.

That fixture produced a 20-slide editable deck instead of 21 slides. Every
original observation was unchanged. All rendered pages were visually inspected;
automatic rendered-page QA found no issues. Its original incomplete coverage
warning remains because the saved annual topic selection was not reclassified
by a live model. The next fresh analysis exercises the expanded coverage review.

Regression coverage includes exact transport round trips, duplicate evidence
membership, bounded review completion beyond three calls and rollback, header
spacing/currency/denominators, competing table rows, table unit restoration,
qualifying evidence retention and summary page capacity. Completed and analysis
caches advance to v95 / analysis-v49; extraction remains extraction-v4.
