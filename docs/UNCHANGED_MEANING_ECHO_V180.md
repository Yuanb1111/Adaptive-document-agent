# Unchanged protected meaning echoes (v180)

The v179 checkpoint ending `.639` stopped in `introduction_editorial` with
`Meaning resolution edit has an unknown, duplicate or unowned current meaning ID`.
The complete resolution response proposed three edits for two meaning findings.
Two edits addressed the exact finding-owned meanings. The third echoed a different
current meaning from the same affected source part, with exactly unchanged wording
and an empty evidence field. The validator rejected that protected ID before the
fresh independent review could run. This was not a schema parse or truncation error.

The resolver now ignores an echoed protected meaning only when its ID exists in
an affected included part, it contains exactly one assertion with byte-for-byte
equal wording, and its proposed quote is empty or exactly the existing quote.
The original meaning and evidence are retained. There is no text normalization,
semantic matching, deletion or permission to rewrite protected copy. Unknown and
duplicate IDs, unrelated or omitted parts, conflicting evidence, extra assertions
and any changed protected wording still fail. An ignored echo is not a changed
meaning and cannot satisfy a corrected disposition. All finding ownership and
disposition checks still apply.

The request now supplies explicit `editable_meaning_ids` and tells the author not
to echo unchanged meanings or claim to remove them when attaching their qualifiers
elsewhere. Raw responses remain intact. Successful audits and the historical
resolution ledger record `coalesced_unchanged_meaning_ids`. The independent review
still receives the actual revised union, original decisions and proposed reasons;
it must judge those reasons against the source, including any inaccurate claim
that an unchanged meaning was removed. Protocol validation is never acceptance.

The saved `.639` response passes the production resolver's offline replay with
two findings, three proposed edits and one ignored unchanged echo. No model calls
were made, and the source checkpoint was not rewritten. The follow-on independent
semantic review and reporting/export have not been replayed with a live model.
Synthetic tests cover both acceptance and rejection by the final fresh reviewer.

Local introduction, compact-summary, pipeline and overview regressions pass with
354 passed and one optional recorded-artifact replay skipped. A separate group
covering chunk recovery, final claim QA and finalization passes all 26 tests.
The attempted full Windows suite was interrupted at a Streamlit AppTest stall;
it is not counted as a complete pass. Its six earlier chunk-cache path failures
were reproduced and resolved by using a short test temporary directory, without
changing product code. The complete suite, including UI tests, remains in Linux CI.

Replay with `python -m scripts.replay_meaning_resolution <analysis.json>`.
The pipeline version advances to `2026-10-23-unchanged-meaning-echo-v180`;
extraction and numerical analysis contracts remain `extraction-v23` and
`analysis-v88`. The app must load the new code before retrying the failed analysis.
