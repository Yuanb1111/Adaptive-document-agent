# Editorial briefing and presentation review, v91

The shared Streamlit/PPT briefing now asks the model to lead with the latest
material development and its counterpoint, explain source reconciliations,
attribute estimates, and avoid repeating annual and interim versions of the same
finding. Bounded literal identity excerpts provide company context without new
model calls. External reporting is a writing reference, never document evidence.

The source validator distinguishes reporting-window durations from conditional
outcomes and accepts hyphenated buffer durations. Source quantities still pass
the original evidence checks before Python exactly converts explicit monetary
thousands to millions for display. Rates retain their denominators, and original
briefing text, quotations and observations remain available.

Presentation changes:

- Use one body font across summary continuation pages, balance complete items,
  and avoid repeating the same executive brief in Conclusions. Unresolved source
  checks and incomplete coverage remain visible on Review status; the prior
  closing plan remains in notes.
- Bind narrowed headings to selected measures and synchronize the section and
  appendix labels. Preserve the latest turning point in factual subtitles,
  including when a long original title is moved out of the title area.
- Calculate chart annotations over an explicitly named endpoint interval, or
  the latest comparable interval otherwise. Match ISO dates and audit markers,
  keep per-unit denominators, and use integral display for integral counts.
- Keep continuous date-axis spacing and add exact date/value point labels for
  small single-series charts. Keep calendar ticks and the native workbook.
- Expand generic percentage-of-total labels only using the explicit caption of
  the same source table. Scope generic interim assurance caveats to identified
  columns; unknown assurance status remains unknown.
- Omit wholly repeated chart-support tables while retaining partially overlapping
  tables and full provenance. Use up to two monetary decimals in the appendix,
  preserving small-value precision. Pack complete table prefixes onto available
  pages and merge repeated source footers without joining different period tables.
- Balance cover line breaks and label source-document images with their page.
- Give failed coverage-batch repairs the exact deferred IDs and an explicit
  selectable-ID list. Invalid or unfinished semantic review still fails closed.

The local replay of analysis67 preserves all 1,470 observations and produces an
18-slide deck instead of the supplied 20-slide deck. The local Artifact renderer
rendered every slide; automatic visual QA returned no issues. This replay uses
the saved brief and topic selection, not a new model-generated editorial brief.
It does not turn the saved incomplete coverage review into a completed review.
Regenerate the analysis to apply the new semantic writing and selection prompts.
Downloaded PPT/JSON files are not modified in place.

Validation: 3,020 regression cases passed across the complete run and targeted
reruns; eight Linux/opt-in integration cases were skipped. The final complete
run passed 3,017 cases; its three remaining failures were missing `pytz` in the
temporary test environment. After installing that pandas dependency, all 48
targeted report/editorial/chart/caption tests passed. Streamlit interaction and
real adapter isolation tests ran with local loopback available and model HTTP
intercepted; TLS/tokenizer resources were initialized before environment isolation.
