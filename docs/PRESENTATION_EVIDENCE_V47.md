# Evidence and source previews (v47)

This update applies to the agent's shared extraction, validation and presentation
paths. It contains no issuer-specific names, source page numbers or financial
values in production logic and makes no additional model requests.

- Closing pages bind the model's existing conclusions/watch items to their
  explicit observation or analysis-input IDs. Compatible period sequences may
  share a page; different units keep separate tables. Unmatched or oversized
  content retains the complete pagination fallback. Full raw records remain in
  notes.
- A resolved company name with retained source-page references supersedes
  stale identity-unknown notes in the presentation. Original profile notes stay
  in JSON. Independent risk qualifications and conflicting identity evidence
  remain visible.
- Extraction restores literal parent headings supported by matching named
  subtotals, and explicit table-caption subjects for generic bucket labels.
  It preserves IDs, metric labels, raw values, units, periods and evidence.
  Different page/table IDs alone never exempt records from conflict checking.
  A single original name cannot trigger the differently-qualified-name warning.
- Comparative copy retrieves reported shares from the selected source row,
  table, scope and periods. Category rankings need an explicit common-total
  percentage column and complete peer values reconciling to 100% within rounding
  tolerance. Expense ratios are insufficient. Subject/direction checks prevent
  another category's series from supporting a claim. Missing or ambiguous
  evidence narrows the presentation wording while retaining independent caveats.
- A hash check binds first-page artwork to the analysed PDF. Export prefers a
  substantial original embedded image, avoiding separately typeset cover titles
  and company details. If none is available, it renders the complete first page
  with a bounded long edge. Artwork keeps its proportions and appears once in
  the introduction, with its citation in the page footer and speaker notes.
  There is no separate caption below the picture. A lengthy introduction is
  paginated rather than silently dropped. Optional custom artwork remains
  available for the cover.

`PIPELINE_VERSION` is `2026-09-28-source-evidence-v47`. The completed-result and
PPT caches are invalidated. Extraction and model-request cache versions remain
unchanged: raw table parsing is unchanged, and changed model request contents
already participate in request hashes.

## Verification

Focused synthetic regressions cover same-parent conflicts across pages,
different-parent generic labels, raw-record preservation, percentage columns,
ambiguous contexts, ranking/denominator/direction failures, multi-subject claims,
identity caveats, closing-period separation, source-PDF mismatch, scanned/vector
previews, introduction overflow and readable comparison labels.

The offline JSON27 replay retains all 1,475 original records and their numeric
facts. Fourteen false conflict warnings and one single-name normalization warning
are removed; 126 independent coverage warnings remain. The deck changes from
20 to 18 pages. The first-page source image appears on page 3, the comparison evidence
appears on pages 7–8, and the four former closing/evidence pages become two.
The replay calls no model and preserves the downloaded input files.

Local Artifact rendering and the export gates check every page. This is not a
native PowerPoint compatibility certification. Missing explicit table context
continues to produce conservative warnings; uncertain comparative language is
narrowed rather than supported with invented categories or denominators.

Final verification: **1,330 tests passed, 3 skipped**. The 18-page offline deck
passed the financial and rendered export gates with no visual issues or repairs.
All 1,475 raw numeric records and 95 original profile notes remain intact in JSON;
superseded identity text is absent from the presentation's speaker notes.

The subsequent original-photo adjustment passes all 39 related regression tests.
Its 18-page replay passes the rendered export gates without issues or repairs;
slide 3 embeds the selected original JPEG byte-for-byte, with no crop or separate
caption. This replay also makes no model requests.
