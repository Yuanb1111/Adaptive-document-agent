# Current review and topic recovery v200

Two v199 diagnostics expose different generic protocol boundaries. These changes
depend on current assertion identity, source ownership and physical layout, not
document type, issuer, source page numbers, dates, product names or financial values.

## Unchanged proposed correction

The `.151` run stopped after approximately five minutes during introduction
editorial review. A finding alleged an unsupported date in the current assertion,
although that assertion no longer contained the date. The next resolution twice
returned the exact unchanged assertion with a `corrected` disposition and a reason
claiming to remove the date. Another finding in the same response had a real edit.
The existing no-op guard correctly rejected the claimed correction. Repeating the
complete resolution request did not resolve the disagreement about current copy.

For an explicit, exactly unchanged edit at the identified finding-owned meaning,
v200 uses the existing single protocol retry for a narrow model adjudication:

- Supply the exact current and proposed text side by side, the finding and proposed
  reasons, with the original complete source and immutable current inventory.
- Require an explicit model choice: provide a real targeted revision or explain why
  the current assertion already satisfies the finding. Python does not infer which
  interpretation is correct, rewrite the assertion or manufacture a qualification.
- Merge only that model-selected edit/disposition into the original response. Keep
  every other edit and finding, revalidate the complete proposal, and still require
  fresh independent review of the entire union and every disposition.
- Preserve the raw first response, targeted decision, merged response and request
  context. Wrong identifiers, empty/unchanged revisions, invalid already-covered
  proposals, privacy failures and cancellation cannot become acceptance or another
  retry. The ordinary correction path remains for other missing-mutation failures.

The private replay reaches the fresh adjudication request using the original first
response, retaining both findings and unchanged source/selection. No adjudication
was recorded, so the replay stops there and makes no provider request.

## Retain selected topics after an unbound ratio claim

The `.482` run completed in approximately 13 minutes 15 seconds and exported a
20-slide deck: five introduction body slides, eight analytical slides, and two
data-index slides. Its presentation plan was nevertheless marked degraded. One
ratio-pronoun claim in the selected-topic summary failed directional binding, and
that error discarded the entire five-topic plan. The fallback lost the selected
relationships between measures and used mostly generic metric captions.

Ratio binding failures now retain structured slide/component/bullet addresses.
The existing source-scope recovery can withdraw only the affected topic's assertion
to its original neutral question, with the exact complete evidence ownership
required for summary binding. It retains other selected topics, audits the original
claim and prevents later summary rebuilding from reviving it. Ambiguous ownership
and newly introduced validation errors still block recovery. This does not declare
an unparsed verb or unresolved ratio assertion correct.

An offline replay retains all five original topics without changing observations,
model selections, insights or model usage. The recovered plan introduces measures
absent from the old exported fallback. The normal audit-scope gate correctly blocks
re-export until their assurance review is complete. No synthetic approval or
replacement finished PPT is supplied from that stale review state.

## Readability and existing deck checks

Date-axis tick density now accounts for label length, font size and available
physical width. Calendar spacing, exact dates, workbook values and source-point
labels remain unchanged. This avoids the crowded quarterly full-date labels seen
in the saved inventory chart.

The saved deck was rendered locally and all 20 slides inspected. Its nine native
charts contain 31 points, whose signed values and periods match their retained
analysis inputs at the displayed scales. All 12 product-composition percentages
also match the retained values. This is a deck-to-analysis consistency check, not
a new audit opinion or certification of every narrative claim against the PDF.

## Validation

Focused regressions cover topic compilation/recovery, preserved unrelated topics,
source ownership, durable claim withdrawal, exact unchanged correction handling,
explicit model disagreement, independent acceptance/rejection, preserved companion
edits, terminal invalid responses, privacy and cancellation. Date-axis tests cover
both available width and larger font sizes without changing series values.

The complete local Windows suite passed 5,857 tests, with 14 opt-in Linux/private
checkpoint skips and four existing dependency event-loop warnings. The 18 new
focused cases passed again after clarifying the targeted request's schema-only
system instruction. Python syntax and whitespace checks passed. The saved deck's
two date charts were restyled through the production axis function and all 20
pages rendered locally; serialized series data was identical before/after, and
the inventory chart's full-date axis labels no longer overlapped.

```text
python -m scripts.replay_unchanged_correction path/to/analysis.json
python -m scripts.replay_topic_recovery path/to/analysis.json
```

Both replays read private inputs in place and make no model request. They prove
the stated controller transitions only. Live model correction, independent review
and final export still require a fresh run. Extraction and analysis cache versions
are unchanged; the pipeline identity is
`2026-10-26-current-review-and-topic-recovery-v200`.
