# Source-bound Summary, Chinese prose and original appendices (v105)

The customized v104 run produced analysis JSON but no PPT: a source-footer
collision blocked the final visual gate. The default run exported but its
complete Summary reading never became introductory slides. Custom prose discovery
depended on a full export build, allowing an unrelated table/layout failure to
prevent translation. Some raw tables were also discarded by analytical scoring.

## Changes

- `SummaryEditorialDraft` selects compact IDs from the validated reading facts.
  Python fills the literal quote, owning part and exact page. Unknown references,
  unsupported amounts and missing substantive parts remain errors. Schema
  failures receive one correction over the original reading, with raw responses
  and validation causes audited. Final global reading/presentation/export coverage
  checks still require every substantive part; only headings/layout may be omitted.
  A logical introductory page can continue on several native slides when Chinese
  copy needs more room. Every whole item keeps its durable source-part binding;
  physical pagination cannot silently hide or drop a part.
- Numeric tokenization does not bind a final year to a percentage on the next
  header line or treat a range separator as the second endpoint's negative sign.
  Real negatives retain their sign. Point-date evidence preserves multiple date
  headers on one line and their literal column periods, avoiding a fabricated
  annual date for an interim column.
- Brief meaning review accepts complete literal currency/scale endpoints while
  still rejecting rescaling, unsupported endpoints and wrong direction. Repair
  options for positive loss/outflow magnitudes include the exact required signed
  source annotation. Meaning reviews and failures are available in the JSON audit.
- Localization inventories only private composed prose, independently of raw
  source-table layout and export preflight. The actual export retains all gates.
  Translation and independent review cover each exact copy ID; numeric/scale
  checks and native text capacity also apply. Only failed IDs receive one retry;
  verified translations are never overwritten. Specific discovery/schema errors
  remain in `report_localization_audit`. Wide characters count appropriately for
  introductory page density rather than requiring padded Chinese copy.
- Raw physical tables are retained independently of analytical candidate scores.
  Deduplication needs equal IDs or overlapping geometry with literal cell
  containment. Numeric prose suffixes are not single-column table cells. Raw row
  footnotes, vertical period headings, original units and audit qualifications
  survive editable appendix pagination and post-export cell verification.
- Appendix source-footer space respects inherited template footers, including
  when packing short tables. All prose sanitizers preserve literal appendix
  cells and source context. Informational borderless recovery alone no longer
  implies ambiguous extraction; genuine ambiguity/OCR limitations remain visible.

## Verification

Regressions cover schema repair and failed repairs, complete part ownership,
currency/scale/sign/date gates, independent Chinese localization with a failed-ID
retry, wide-character density, original source sanitizer immunity, single-column
tables, vertical periods and physical inventory retention. Existing insight
truncation recovery and download/tab navigation regressions remain applicable.

A private offline replay of the supplied v104 files checked all 109 read parts,
59 substantive parts and 106 source facts without reading validation errors.
Re-extracting all 53 requested chapter pages retained 37 table fragments, compared
with 35 previously: the additional source regions were equity and foreign-currency
sensitivity. Every retained cell was verified in the editable appendix. The
70-slide replay passed all-page Artifact rendering/visual QA on its first attempt
with no critical findings. This replay tests source extraction and export; it is
not a new online model run or a certification that arbitrary PDF detection can
never miss a table. Private PDFs, JSON and replay decks are not repository fixtures.

Full offline regression: 3,233 passed, 8 skipped, zero failures/errors, including
all four SDK transport mocks previously affected by missing tokenizer assets.
The additional actual-template copyright/footer regression also passed. The
SDK test environment retains Windows infrastructure variables while scrubbing
provider credentials; the public tokenizer fixture is checksum-verified locally.
No live document/model request was made. Optional external renderer/font cases
remain skipped; the private real-deck Artifact replay above was run separately.

`PIPELINE_VERSION` is `2026-10-10-source-bound-summary-chinese-appendix-v105`;
extraction is `extraction-v8` and analysis is `analysis-v57`, so stale results and
selected-only raw inventories are not reused after deployment. Restart the app
and confirm the displayed pipeline version before the next online comparison.
