# Special visual header capacity recovery (v81)

A saved v80 analysis completed successfully but its PowerPoint export failed
while building a comparison matrix. The selected slide message exceeded the
template's readable subtitle capacity. Ordinary composed slides already moved
excess copy into commentary; matrix, waterfall and horizon renderers passed the
entire message directly into the fixed header instead.

These three renderers now share a header preparation and continuation helper.
It retains complete sentences that fit the subtitle, then paginates all remaining
copy as editable commentary at the established body font size. An oversized
title uses the planned section heading, or a neutral Analysis heading, while the
complete original title remains visible in commentary. The planned slide and
source observations are not modified.

The native visual remains intact. Continuation pages carry visible source page
references and notes containing the full original plan and source observations;
horizon notes also retain the quoted future-obligation evidence. Matrix row
pagination remains separate from commentary pagination, so the latter appears
once after all matrix rows. Short headers add no pages. Invalid evidence still
fails validation before rendering; the change does not bypass financial,
preflight, brand, or rendered layout checks.

Synthetic regression tests cover all three visual roles, long single sentences,
multiple sentences, multiple continuation pages, oversized titles, exact visible
copy, native table/chart data preservation, evidence notes, source footers,
geometry, unchanged short headers, and rejection of invalid evidence. The saved
analysis and its source PDF are local diagnostics and are not committed.

Validation: 506 presentation, export, brand and related regression tests passed.
The saved analysis completed the full evidence, native preflight and local
Artifact rendering gate, producing 27 slides with 15 native charts and 12 native
tables. All 27 rendered pages were visually reviewed. The final offline export
took 20.359 seconds without model calls; this is a local replay measurement,
not a hosted performance guarantee. Native preflight retained a nonblocking
wording warning on an existing coverage slide; rendered QA reported no issues.

The pipeline cache version changes to v81. Extraction and analysis cache
contracts remain unchanged because this changes presentation layout only.
