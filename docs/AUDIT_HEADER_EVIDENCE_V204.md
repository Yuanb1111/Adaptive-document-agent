# v204: continuous audit-header evidence

The v203 analysis export ending in `101735.496.json` stopped in
`report_audit_scope` after 709.9 seconds. A rejected unknown disposition led to
a proposed audited counterpart. Its first header quotation omitted intervening
text from the original multiline header. The correction then copied a literal
duration line but omitted the reporting year. The binding validator correctly
rejected both proposals; the existing correction budget was exhausted.

The source page contained the required year and duration. This was an evidence
quotation failure, not a provider timeout or an absent source value.

## Change

- Initial target contracts expose the retained period and require a continuous
  header passage containing both the duration/date tiers and year row.
- Writer, reviewer and correction instructions retain intervening text, adjacent
  column headings and line breaks rather than joining disconnected fragments.
- For a failed header quotation, correction feedback includes up to four literal
  reading windows on the model-proposed header/value pages. Each window preserves
  exact character offsets and whole lines around the retained year. Windows over
  1,800 characters are omitted with a count, never clipped or joined.
- Windows are untrusted reading aids, not approved headers. The full source pages
  remain available. Python does not choose column ownership or assurance status,
  rewrite a binding, change raw facts, or grant semantic approval.
- Existing binding validation, independent review, correction limits, Local Only
  routing and incomplete-run behavior are unchanged.

## Validation

Synthetic tests cover noncontiguous headers, missing years, the original sequence
of unknown rejection followed by malformed-header correction, continued rejection
by the independent reviewer, unavailable source pages, bounded reading windows,
and unchanged source data.

Focused regression result: **362 passed, 5 skipped** across audit evidence,
correction budgets, source discovery, reporting checkpoints, failed/interrupted
reruns and the LLM gateway. Skipped tests require external checkpoint fixtures.

An offline replay of the private `.496` export reproduced both original header
errors. The new feedback supplied a literal page-429 window that satisfies the
existing binding checks in both cases. The input file's SHA-256 was unchanged.
This replay made no model request, supplied no new independent semantic approval,
and did not regenerate the presentation. Fresh end-to-end model validation remains
necessary to establish the outcome of a new run.
