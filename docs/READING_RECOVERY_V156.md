# Introduction reading recovery and period scope (v156)

A content correction can return malformed JSON even after the first response
parsed successfully. Reading now has separate budgets: two semantic readings,
with at most one format-only repair for each malformed, non-truncated response.
Missing-range and rejected-span readings use the same format recovery boundary.
All calls, admission, cancellation, privacy enforcement and usage accounting
remain in `LLMGateway`. There is no provider fallback.

Format repair retains the invalid response and correction in the reading audit.
A conservative content comparison rejects changed scalar content, added fields,
or a changed valid JSON structure. Parsed repairs still undergo source binding,
fact validation and exact line-coverage checks. A format repair is never an
approval of the evidence. Truncated output cannot be repaired this way.

Successful reading batches have a separate validated cache, so a failed sibling
does not require purchasing those readings again. Keys bind source blocks,
document identity, reading rules, analysis contract, provider, model, endpoint,
privacy, temperature and request policy. Every reuse reruns current evidence
validation. Failed batches, cache-disabled runs and changed identities cannot
reuse an accepted batch. Cached readings do not certify later editorial copy.

Partial results export `failed_stage` and `failure_details`, including the
reading operation and source pages. These describe the actual failure;
`retry_from` continues to describe the foreground resume point. Progress and
the incomplete-result view display the located introduction failure.

Analytical source-table copies now retain the distinction between leaf years
under aligned annual, month-duration and snapshot superheaders. Only literal
cells or retained source spans establish ownership. Missing or conflicting
group ownership quarantines the analytical copy while preserving the complete
literal source grid. Explicit note/reference columns remain source metadata
and do not become numeric measures.

The extraction contract advances to `extraction-v22`, analysis to
`analysis-v80`, and pipeline to v156. Restart the application and run a fresh
analysis from the original PDF: old observations and retry checkpoints cannot
recover already-flattened period metadata.

Verification includes synthetic tests for semantic correction followed by
malformed JSON, independent format/semantic budgets, changed-content rejection,
truncation, cancellation, successful-sibling cache reuse and revalidation,
failure-stage serialization, annual/interim periods, snapshot dates, conflicting
spans and reference columns. An offline replay of the retained `.290` responses
validated all six source-reading batches (97 parts) after one deliberately
corrected punctuation fixture, and checked the original page 402 grid. This
replay makes no provider calls and does not certify new live model output or a
complete regenerated presentation. Source documents and replay outputs remain
outside Git.

Fresh geometry extraction from the matching source PDF also checked pages 402,
403, 404, 407, 408, 409 and 410. Complete, uniquely aligned snapshot phrases
remain together instead of splitting their words across adjacent year columns.
Annual/interim periods and balance-sheet dates resolved without quarantining
these seven tables; their literal grids remain unchanged by analytical copying.
