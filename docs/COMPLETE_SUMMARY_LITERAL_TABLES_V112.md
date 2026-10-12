# v112: complete introductory scope and literal source tables

## Observed failures

Both v111 comparison runs omitted the introduction after page selection failed.
The exact-heading matcher missed a compound Summary heading, and distant
discovery anchors exhausted the candidate budget before introductory pages.
The custom appendix exported only the previously retained fragments, then
treated unchanged exported cells as proof that all original tables were present.
This did not detect missing tables, normalized or misplaced headers, omitted
subtotals, incomplete notes, or incorrect source-page references.

## Changes

- Recognize compound introductory Summary headings and complete outline ranges
  as retrieval hints. Explicit scope cannot be truncated by the preview budget;
  early document pages precede distant discovery anchors. Model-selected ranges
  still determine meaning for differently named sections. Record candidate,
  selection and complete-reading pages in the run audit.
- Require the compact writer's first page to explain the actual subject,
  products/services and scope. The existing independent semantic reviewer must
  explicitly accept that opening as well as every substantive part. Names,
  financial results, topic lists and nominal part-ID attachment are insufficient.
  Block final export when a pipeline introduction failed or complete introductory
  coverage has no visible pages. No heuristic business profile is substituted.
- Build literal ruled grids from PDFium-decoded glyphs and MuPDF vector/font
  geometry, including crop offsets and rotated reading directions. Preserve
  source header tiers, proved merged spans, units, periods, wrapped labels,
  blank-labelled subtotals, dashes, missing-value text and annotations. Derive
  analytical copies separately; their mutations cannot alter source grids.
- Keep legacy bordered/aligned recovery for other layouts, including separate
  unruled grids on a page with a ruled grid. Do not promote unchecked fallback
  layouts to complete-source verification. Reject list/footnote markers as a
  standalone label column; narrowly recover two-row quantitative aligned grids.
- Carry a page-level ruling inventory and immutable grid/annotation digests
  through parsing, caching and analysis. Completeness status now depends on that
  source inventory separately from PPT cell transport. Unchecked or changed
  layouts remain partial rather than receiving a false satisfied verdict.
- Repeat original header tiers visibly, preserve native merged header spans,
  and split wide tables at proved header-group boundaries when available.
  Verify native cells, complete footnotes, metadata pages and actual visible
  physical PDF page footers, including packed pages and Chinese footers.
  Period-specific qualifications stay in their original header cells; do not
  duplicate them into a whole-table caption that expands their meaning.
- Cache source-table packing metadata and geometry for each retained slide;
  avoid repeated XML scans and full source-note JSON decoding while searching
  earlier slides. Prefer decoded ruled extraction over repeated legacy parsing
  when no separate aligned outside data needs recovery. Localize the English
  rounding display wrapper without changing source cells or annotations.

All semantic decisions still use LLMGateway. New extraction/packing work is
local and deterministic; it adds no provider, network fallback or document-type
workflow. Pipeline v112, extraction v12 and analysis v64 invalidate incompatible
retained results rather than reusing the v111 omissions.

## Verification

The full local suite passes 3,362 tests with 8 skipped in 345 seconds. The final
period-qualification correction passes 103 focused regressions. Five
non-failing diagnostics concern preloaded pytest plugins, SDK deprecations and
Windows event-loop cleanup. The SDK credential regressions retain their network
interception and use preloaded public tokenizer data for offline execution.

Synthetic regressions cover compound headings with distant anchors, mandatory
opening acceptance, full part coverage, rotated tables, tightly spaced adjacent
headings, year headers above short dash values, merged headers, first rows,
subtotals, N/A, multiline notes, mixed ruled/unruled layouts, source immutability,
and tampered cells, page metadata and visible table/annotation footers.

The private PDF comparison uses the original 776-page source. Its 91-page
requested chapter independently contains 72 physical table blocks on 53 pages.
The new inventory agrees on every page, has no unresolved source-layout audit
errors, and excludes the former list/footnote false positives. All 72 tables and
their annotations survive editable native save/reload; 162 readable appendix
pages pass local full-deck rendering diagnostics. Original raw tables, page text,
review images, dependency caches and exported decks stay in ignored local output.

These are local extraction, transport and rendering checks, with mocked semantic
regressions. They are not a new hosted-model comparison or a measured cloud
end-to-end speed claim. A fresh v112 run is needed for independent model coverage
review and the requested-language body. Unruled, scanned, ambiguous or unusual
layouts can still require review; detected-region agreement is not a universal
certificate that a PDF contains no other tables.

The local packing comparison clones the same 175-slide, 72-grid input for both
implementations: v111 packing takes 157.32 seconds, v112 takes 1.52 seconds; both
retain the same 170 pages and pass the 72-table cell/annotation checks. This
measures only table packing, not authoring or cloud requests. On the same
91-page chapter, the v111 extraction implementation takes 20.45 seconds versus
17.84 seconds for v112; these local stage measurements do not imply an equivalent
whole-run speedup.
