# Summary line assignment and PPT export (v114)

Both v113 exports, customized analysis 95 and standard analysis 96, completed
candidate scoring and report analysis. Both PPT exports were blocked because
the introductory Summary reading failed exact source-line assignment. Neither
run reached compact Summary writing. The v113 scoring truncation recovery did
work: successful scoring requests followed the recorded length failures.

The saved reading audits isolate the fatal batch to physical PDF pages 12–13.
In 95, whitespace lines were unassigned and one footer line was assigned to
both a content part and a separate layout part. In 96, whitespace and the final
footer line were unassigned. The fatal line-coverage gaps did not contain body
paragraphs. Other initial fact/quote validation failures had been handled by
the existing bounded rereading and internal literal-evidence capture.

## Repair

The reading binder now accounts for whitespace-only gaps deterministically,
retaining their exact block, line, page and source text. It removes a no-fact
layout record only when every line is already owned by another retained part.
Content spans, fact quotations and substantive overlapping records are never
trimmed or discarded. Original model responses and every mechanical adjustment
remain in the reading audit.

Each attempted reading now records exact missing, overlapping and out-of-range
line numbers. The existing one full-batch correction receives these details.
If the second response passes all other checks and only nonblank gaps remain,
one additional, bounded missing-range reading asks the same configured gateway
to classify and read those exact ranges. The complete original blocks remain
available as context. The response cannot touch accepted lines, change existing
facts, overlap, cite an unknown block, or leave content without supported facts.
There is no recursive patching, model fallback or repair of truncated JSON.

Python does not guess that a short or numeric line is a footer. Nonblank gaps
remain a semantic model decision. The complete reading, independent editorial
review, business opening requirement and PPT export gates remain required.

Pipeline marker: `2026-10-12-summary-line-coverage-recovery-v114`. Existing
extraction/analysis schemas and unrelated successful model request caches are
unchanged. The initial reading prompt is reusable; corrected feedback includes
the new exact coverage details.

## Evidence and validation limits

Offline replay of all saved reading responses from 95 passes the complete
12-page reading validator, retaining 59 substantive parts. For 96, replay plus
one explicitly simulated model classification of the missing physical-page-13
footer passes with 57 substantive parts. The simulated footer reply is a local
regression fixture, not a hosted model result. Private source files, exported
JSON and replay receipts stay in ignored local output directories.

Synthetic tests cover whitespace, duplicate layout, genuine missing content,
substantive overlap, invalid patch ownership, unsupported facts, privacy errors,
and arbitrarily large invalid line endpoints. An integration test proceeds from
recovered reading through model-authored introduction fixtures to native PPT
serialization/reload, checking business copy and source notes. No new live
model generation or completed hosted deck is claimed by these tests.

Validation: 279 related Summary/introduction/export/finalization/pipeline tests
passed, with five existing skipped tests and one pytest plugin pre-import
warning. A separately added missing-range truncation regression also passed
(280 passing tests in total across these non-overlapping checks).
