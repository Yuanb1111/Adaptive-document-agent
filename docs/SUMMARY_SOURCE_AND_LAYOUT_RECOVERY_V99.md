# Source and layout recovery (v99)

The two latest reviewed exports were PPT 56 / analysis 73 (Geek+) and PPT 57 /
analysis 74 (Dobot), both produced by v98. All 43 original slides were rendered
and inspected. Both complete Summary readers failed schema validation, leaving
no verified introduction. Both editorial briefs were unavailable in the final
result, so the exporter displayed a repetitive series-level numeric fallback.
The second run discarded a repaired brief because source-scope reconciliation
changed presentation topics after concurrent briefing had started.

## Source accuracy and reading

- A standalone unit heading inside a table, such as `(In millions of RMB)`, now
  scopes subsequent rows. It cannot change preceding counts, and another
  metric's unit or a narrative sentence cannot act as such a heading. Explicit
  cell/row units remain more specific. The heading stays in the raw source grid
  and is no longer prefixed to metric names as a semantic category.
- Re-extraction of the actual source table on Geek+ PDF page 30 preserves the
  native amounts 726.83, 1,506.66 and 1,792.43 RMB million. These are normalized
  to base currency once, then shown at the corresponding appendix scale. The old
  observations had unknown source units and incorrectly appeared as tiny
  million-denominated values. Cached JSON is not silently rewritten.
- Brief table evidence uses the same scoped declarations, provided they occur
  literally in the supplied source context and the complete row binds uniquely.
  Competing rows with different scoped units remain ambiguous. Existing safe
  column metadata still outranks an unrelated currency elsewhere in the header.
- Summary wire facts cite line spans rather than retransmitting source quotes
  and page numbers. Python derives the literal quote/page from the exact block.
  Every source line is still partitioned and checked; each part is read before
  model-authored include/merge/omit decisions. Batches retain all source content
  but are bounded at 12,000 rather than 24,000 characters.
- A schema failure retains raw output and its detailed validation cause and
  permits one targeted correction unless the response was truncated. Line gaps, overlaps, invalid quote spans,
  unsupported quantities and missing editorial decisions still fail validation.
  Transport/privacy failures never trigger a provider fallback.

## Editorial and layout

- Source period/category definitions and audit qualifications are reconciled
  before concurrent briefing starts. The prepared-brief input-change guard and
  final source validation remain strict; genuine changed evidence is rejected.
- Failed brief repair can retain two independently verified findings when the
  existing source/topic-coverage gates pass. Original locks, discarded items and
  failures remain audited. No filler is manufactured to reach three items.
- Native money options include an exact ready-to-use spelling; the repair prompt
  also covers rounded numbers in labels, signs and required magnitude annotations.
- Failed introduction placeholders are omitted from slides and the agenda, while
  the actual failure remains in diagnostics/notes. This is not certified Summary
  coverage: a complete reading must still succeed before introduction pages exist.
- Short single-row closing continuations can fold into a substantive page,
  retaining their copy, table and source notes. When space exists the table stays
  visible on the destination page; complete raw records also remain in exports.
- Appendix packing can use earlier free space while keeping independent period
  headers, whole tables, font sizes, values and source notes intact.
- Generic comparison headings use the displayed measure names. Single-chart
  continuations use that chart's heading and do not duplicate the earlier
  commentary or global takeaway. Full source-bound ratio formulas appear once;
  only complete duplicate division statements are removed, not extra conditions.
- Coverage review also bounds the number of output decisions per request (32),
  preventing a short input from demanding an oversized response. Every candidate
  still needs a decision, and an incomplete transaction preserves the prior valid
  selection with a diagnostic. Exact period labels are requested rather than
  unsupported replacements such as `1H` for an unspecified six-month interval.

## Validation and limits

Focused regressions cover malformed Summary responses, exact line quotes,
source unit scope, competing row units, strict money checks, prepared topic
stability, two-item verified brief recovery, closing/appendix packing and ratio
definition conditions. All model calls remain behind LLMGateway and the existing
Local Only privacy rules.

Final Windows regression run: 3,125 passed, 8 skipped and 3 deselected in 226.93
seconds. The three real Gemini transport probes require offline tokenizer data
unavailable in the local test runtime; they remain enabled in GitHub's full
Linux suite, including the real LibreOffice renderer. Final layout-focused
checks also passed (45 tests). Local transport-mock/asyncio warnings do not
change these outcomes; no isolation checks were weakened.

Both recorded results were replayed through the actual exporter and Artifact
renderer for layout QA (21 and 18 pages), plus two source-unit regression pages.
Those replay decks preserve the old recorded analysis/model content and are
private QA, not fresh analyses or replacement deliverables. The source-unit
regression uses newly extracted literal table data. Original and replay slides
were inspected, and material unit/pagination changes were checked separately.

The original runs spent roughly 112–184 seconds in failing Summary batch calls,
with 33–65k characters of response text and substantial deep reasoning. Reading,
candidate scoring, insights and semantic topic selection continue to use their
deep/default reasoning. Previously approved lightweight writing/layout stays in
place. Smaller reading responses and fewer avoidable validation failures should
reduce wasted work, but no fresh provider run or end-to-end latency improvement
has been measured in this code review. The two original upload-to-download tests
took over eight and nine minutes. Do not advertise a new generation-time target
until a fresh deployed upload confirms it.

Pipeline/extraction/analysis cache contracts advance to v99, extraction-v6 and
analysis-v53. A fresh upload after deployment is required for source extraction,
Summary reading and new editorial responses.
