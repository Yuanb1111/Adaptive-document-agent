# Preserve Summary page context and literal reading evidence (v116)

## Evidence from standard run 99 and customized run 100

Both v115 runs processed the same 432-page PDF. Their Summary scope was physical
PDF pages 9–18. Both stopped before report writing because the background
introduction had failed; the UI's 73% position reflected this checkpoint.

The fatal revenue table on page 10 straddled the reader's 6,500-character block
boundary. Its year/percentage header ended the first block; the units, values
and footnote began the next. The schema required facts to cite one part within
one block, so correct references to those years could not bind to the data.
Page 17 similarly split a proceeds allocation from the continuation describing
its purpose. Separately, page 16's table header exceeded the layout length test
because hundreds of alignment spaces were counted as substantive text.

Run 99 took 466,392 ms; run 100 took 672,403 ms. Candidate scoring consumed
103,328 and 313,465 ms respectively, despite the independently failed reading.
The export diagnostics also classified the introduction failure as financial
QA when unrelated extracted-table alignment findings were present.

## Changes

- Preserve a whole source page when it fits the existing 12,000-character
  reading request budget. Larger pages retain bounded, lossless blocks. Raw
  text and source pages are preserved; new character offsets and line ownership
  are verified against the original text.
- Test layout length using whitespace-normalized visible text. This changes
  neither the preserved source nor model semantic roles. Long body passages
  still cannot be hidden as layout, and heading line-count checks remain.
- After the bounded reading correction, a model-assigned content passage with
  no safe paraphrase can retain its complete literal text as `evidence_only`.
  It cannot replace invalid quote endpoints, invent a fact, or bypass reading
  ownership checks. Long evidence is split losslessly within citation limits.
  The editorial model must interpret this material with related content; the
  raw reading-layout fallback and export validator reject unedited evidence
  as slide copy. Summary completion still requires the editorial coverage gate.
- When the existing literal fallback rejects a numeric paraphrase, unsupported
  numeric labels are also quarantined in its audit and replaced with a neutral
  internal label. Rejected model text and labels remain available in the audit.
- Check an already failed background introduction before candidate scoring as
  well as before report writing. Preserve extraction and any completed analysis;
  avoid paying for scoring after this mandatory stage is already known to fail.
- Report early introduction failures as `introduction` in export diagnostics,
  retaining separate financial QA findings without confusing them with the
  stage that actually stopped this run.

Pipeline marker: `2026-10-12-summary-page-evidence-v116`. Updated prompt/source
payloads invalidate affected reading cache entries; unrelated extraction and
analysis cache contracts are unchanged.

## Verification

Offline reading replay uses the actual saved responses from 99 and 100. It
remaps block IDs and line offsets into the joined page blocks without changing
model classifications, notes or claims. Run 100 also reuses its already saved
targeted correction, selecting only whole returned parts requested by the new
repair scope. No new semantic replies are fabricated. Both complete reading
validators pass: 78 total parts for 99 and 90 for 100, with one explicitly
marked literal passage in each. Private source exports and replay receipts
remain in ignored local output directories.

Regression tests cover intact headers/sentences on longer pages, lossless
oversized-page handling, alignment-space false positives, substantive-layout
rejection, evidence-only capture and publication guards, rejected numeric
labels, early scoring cancellation and accurate diagnostic attribution. The
existing native PPT integration test covers recovered reading through authored
editorial copy and PPT serialization/reload.

Final regression: 596 tests passed, with one existing pytest plugin pre-import
warning. This includes Summary, evidence, model gateway, customizations, PPT
export, failure diagnostics and Streamlit tests.

These checks verify the observed reading failure and regression behavior. They
do not establish that a new live provider run has completed compact editing,
full appendix verification, PPT rendering or hosted deployment. Production
latency improvements have not been measured on a completed v116 run.
