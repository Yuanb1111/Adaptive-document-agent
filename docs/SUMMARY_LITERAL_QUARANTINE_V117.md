# Bounded Summary evidence recovery (v117)

## Observed failures

The customized export ending `.864` and standard export ending `.018` both
used v116. They processed the same 694-page PDF, with Summary on physical PDF
pages 10–30. These are different source inputs from runs 99/100 (432 pages).
Both stopped at the early introduction checkpoint, displayed at 66%, before
candidate scoring. Total recorded times were 269,546 ms and 268,121 ms.

The customized run failed on internal reading annotations: percentages such
as `83.6%` did not token-match table cells whose `%` appeared separately in
column headers. The standard run also encountered an 8,059-character literal
quote on page 14 (over the 6,000-character fact limit), a fact citing an adjacent
part on page 13, a layout endpoint one line beyond page 18, and a page 26
heading incorrectly containing a substantive lead-in. The saved targeted
response corrected that semantic classification but its paraphrase still
borrowed years from the following table.

## Recovery contract

- Keep numeric checking for internal annotations. After the existing bounded
  correction, quarantine rejected titles/notes in the audit and pass neutral
  metadata to the editor. This neither accepts their numbers nor changes the
  model-assigned semantic role. Valid facts retain their own evidence checks.
- Split an oversized exact quotation into bounded literal evidence chunks.
  Preserve source words, signs, qualifications, page provenance and the complete
  original source part. The original model fact remains in the audit.
- Mark every rejected paraphrase fallback as `evidence_only`. Retain the full
  assigned passage, including headers and qualifications, rather than handing
  the editor only the possibly incomplete quote that caused the rejection.
- Apply this same quarantine to the existing single targeted correction. If a
  model quote still crosses into another part but references real lines within
  the supplied block, discard its claim and retain only its entire owned
  passage as evidence. Do not borrow the adjacent source. Unknown, reversed or
  out-of-block citations still fail. No extra model retry is introduced.
- Reconcile only a fact-free layout span ending exactly one line past the
  block. Record its original endpoint and retain every actual source line.
  Substantive overlaps, skipped nonblank lines, arbitrary outside endpoints and
  substantive content mislabeled as layout/heading still fail.

No semantic content is classified by Python. The model must still author
audience copy, summarize every substantive part and explain the business on
the opening introduction page. Existing independent compact meaning review,
numeric evidence checks, publication guards, language requirements and appendix
checks remain mandatory. Raw literal fallback cannot substitute for successful
editorial generation.

Pipeline marker: `2026-10-12-summary-literal-quarantine-v117`. The reading prompt
now accurately describes deferred literal evidence handling. Extraction and
analysis cache versions are unchanged.

## Validation

Offline replay uses only the two runs' saved model responses, without creating
new semantic replies. When the repaired scope becomes smaller, it selects only
whole saved targeted-response parts within that scope. Both complete reading
validators pass:

| Run | Assigned source parts | Saved reading calls | Replayed calls |
| --- | ---: | ---: | ---: |
| Customized `.864` | 195 | 24 | 21 |
| Standard `.018` | 181 | 29 | 25 |

The source scope remains all 21 Summary pages. Replayed calls measure avoided
requests on these saved responses, not a prediction of live wall-clock time.
Private source exports and replay receipts remain in ignored local output.

Focused regression: 75 tests passed. Added cases check annotation quarantine,
unsupported factual claims remaining invalid, lossless long quotes, retained
qualifications, cross-part claim rejection, mandatory editorial processing,
and narrowly bounded layout endpoint reconciliation. Existing native PPT
integration tests continue to serialize/reopen authored company introductions.

The Windows sandbox test invocation sets `TEMP`/`TMP` to the workspace's
ignored `output/runtime-tmp` directory. Without this, native export tests fail
when the visual QA gate creates its temporary directory. Tests also use the
existing offline token cache and bundled LiteLLM cost map, avoiding network
fetches during fresh Streamlit imports. These are test environment settings,
not changes to deployed rendering or provider behavior.

Final regression: **917 passed, 5 skipped**. The core suite passed 908 tests
with five existing skips in 119.88 seconds; the nine Streamlit startup/flow
tests passed in 11.31 seconds. Streamlit AppTest required an unsandboxed local
test run because the Windows sandbox stalled its asyncio socketpair before
application code ran (confirmed by a stack trace). No production model call
was used for these tests.

These checks establish recovery of the observed reading failures, not a live
provider or hosted end-to-end PPT success. The exports contain no successful
subsequent editorial responses to replay; actual compact generation, appendix
verification and final PPT export still require a live run.
