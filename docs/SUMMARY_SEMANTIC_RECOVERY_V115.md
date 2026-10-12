# Summary semantic reading recovery and bounded editorial work (v115)

## Observed failures

Customized export 97 and standard export 98 both ran v114 on a 625-page PDF.
Their selected introductory Summary spans physical PDF pages 10–39. Neither
run reached compact introduction writing; both PPT exports were correctly
blocked by the source-verified introduction requirement.

The saved reading responses show a product architecture diagram classified as
layout, qualitative lead-ins classified as content without facts, table facts
whose quotes crossed their assigned part boundaries, and internal labels/notes
exceeding display-oriented schema limits. In 98, relaxing the metadata schema
also exposed invalid table quote spans hidden behind the initial schema error.

Recorded pipeline wall times were 951,296 ms (97) and 554,570 ms (98).
Introduction work itself took approximately 96 and 102 seconds, overlapped
with other stages. Despite its failure, the pipeline continued into expensive
insight writing, topic selection, briefing and, for 97, customization review.
These nested/background timings must not be added as independent wall times.

## Changes

- Internal reading labels, titles and notes retain up to 6,000 characters
  without clipping. Prompt targets remain short; visible slide labels still
  have the 60-character contract. A reading-layout fallback uses neutral short
  display labels when needed and preserves the original internal metadata.
- Reading instructions explicitly cover diagram components, relationships,
  qualitative facts and transitional passages without demanding numeric data.
- After the existing bounded correction, one targeted semantic call may reread
  rejected spans. Accepted evidence outside those ranges remains unchanged.
  Valid in-block quote endpoints can expand the repair range to include whole
  neighbouring parts, allowing the model to regroup table headers with data.
  Python chooses only literal ownership bounds, never semantic classifications.
- Raw replies, rejected parts, expanded scopes, replacement replies and exact
  source-line coverage remain in the audit. Unknown blocks, ambiguous overlaps,
  gaps, out-of-range citations and unsupported facts still fail. There is no
  recursive retry, document-specific classification or cloud fallback.
- Before report writing, a nonblocking checkpoint detects a completed failed
  background introduction. It returns the extracted evidence, completed
  calculations, usage and failure audit while skipping downstream editorial
  model calls. Healthy pending introductions and serial/local ordering are
  unchanged. PPT export rejects this incomplete result before legacy recovery;
  the UI explains that the JSON contains retained diagnostics.
- Independent insight-writing batches overlap at most two requests on eligible
  cloud gateways. Shared gateway admission still bounds total pressure. Source
  order, cache keys, evidence attachment and truncation splitting are preserved.
  Failure cancels pending work, drains in-flight requests, and retains the
  original error rather than masking it with a neighbouring cancellation.
  Local Only and stateful clients remain serial.

Pipeline marker: `2026-10-12-summary-targeted-reading-v115`. Reading prompt/schema
changes invalidate their gateway cache entries; unrelated extraction and
analysis caches retain their existing contracts.

## Verification and limits

Private offline replays use all saved model reading responses from 97 and 98,
including raw JSON previously rejected only for metadata length. They require
two and four explicitly simulated targeted responses respectively. Those
fixtures retain literal diagram/table text and classify the short transition
from its actual wording. Complete line/source validation then passes with 165
and 194 total parts. This proves the repaired binding and coverage path, not
that a live model will return those simulated decisions. Private exports and
replay receipts remain in ignored local output, outside the commit.

Tests exercise diagram/qualitative recovery, retained metadata, bounded repair,
header/data repartitioning, rejected alterations to accepted spans, invented
numbers, missing evidence, privacy errors, early failure diagnostics, cloud
concurrency, stable ordering, caching and cancellation. A synthetic integration
test generates and reloads native PPT bytes after targeted reading recovery,
checking the business opening and retained source content. The independent
compact meaning review and complete Financial Information appendix gates
remain required.

Final regression run: 586 tests passed, with one existing pytest plugin
pre-import warning. Coverage includes Summary/introduction, insight evidence,
gateway admission/privacy, customizations, export diagnostics and Streamlit.

No live provider rerun, hosted deployment completion, end-to-end source PDF
comparison or actual production speedup is claimed by these offline checks.
