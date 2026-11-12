# Timeout .589: scoped rechecks and saved-copy recovery

The November 12 export `analysis_data - 2026-11-12T093113.589.json`
stopped at the shared 900-second analysis deadline. The recorded wall time
was 900,557 ms. Reporting consumed 408,742 ms, of which retained selection
and its corrections consumed 342,688 ms. The executive brief was drafted,
but its independent meaning review remained pending. This was an incomplete
analysis, not a successful report or an individual provider timeout.

The four selection-coverage calls sent 128,579–130,466 input tokens each.
Two of these were local inventory-copy rechecks, yet they retransmitted all
20 findings and unrelated structured evidence. Local copy rechecks now send
only the flagged findings, their calculations, eligible source-table rows,
explicit assurance bindings and proposed copy. All previously supplied
original source pages and layout lines remain available, including related
measures' qualitative qualifications. Full selection review and the final
independent publication gate retain their complete scope. Deterministic
response validation still uses the complete selection; out-of-scope objections
remain recorded for publication review.

The initial offline measurement of this checkpoint gave 356,565 characters for a complete
review request and 172,397 for the one-page local recheck, a 51.7% reduction.
This is a character measurement, not a token count or a latency guarantee.
No original evidence, raw observations or computed results are changed.

The same export contains a saved turnover-days page that fails current numeric
binding checks: its formula explanation introduces day-count constants without
eligible observation rows. Consequently, the old continuation path rejected the
saved presentation and regenerated upstream reporting. A source-identical
reporting timeout now rechecks the saved authored pages before reuse. It routes
only identified copy failures through the existing bounded model correction
and independent copy-review path, freezes the selected priorities and preserves
the other authored pages and the verified introduction. A failed correction
returns partial diagnostics before briefing. Cancellation and privacy failures
still propagate. Remaining presentation validation must pass before reuse;
final meaning, source-integration and publication gates still run normally.

The existing evidence and cache contracts remain compatible so that the .589
checkpoint can be retried. This change does not reset the shared deadline,
grant approval to an old briefing, or introduce a provider fallback.

## Reproduction

```powershell
python -m scripts.inspect_retained_copy_request "path/to/analysis.json"
$env:TIMEOUT_589_DIAGNOSTIC = "path/to/analysis.json"
python -m pytest tests/test_retained_copy_review.py
```

The inspection tool captures requests offline and stops before model-owned
copy repair. Regression fixtures exercise both accepted and still-invalid
corrections, unchanged source data, retained introduction and unchanged pages,
and mandatory subsequent publication review. Synthetic verdicts verify the
control flow only; these fixtures do not certify a real-model run or completed deck.

Validation: the retained-analysis, deadline, catalog-timeout, brief-resume and
cross-page scope suite passed 281 tests with five optional private-fixture
skips. Separately, all three .589-specific replay cases passed with the local
export enabled. `git diff --check` also passed.

## First live continuation

With explicit authorization to send the document evidence to OpenAI, a real
`gpt-6-luna` continuation completed 34 gateway calls in 673.956 seconds. It
successfully repaired the saved page and reused the retained presentation.
The two page rechecks used 48,672 and 48,404 input tokens. Reporting took
87,288 ms and the executive-brief stage took 388,787 ms.

This attempt did not time out, but remained incomplete at source integration:
one disposition selected a 2,368-character line range when its remaining
quotation capacity allowed only 1,800 characters. It had already spent its
semantic correction on other source qualifications. The result and the
real usage ledger are retained under `output/live-589-20261112-01/` locally.

A citation-capacity failure now has a typed error and one addressed reference
correction. The model returns only the affected evidence lists, using the
same supplied source pages; conclusions, dispositions, reasons, quantities and
item indexes stay unchanged. A second capacity failure stops. Invalid source
locators or differing transcriptions do not receive this route. The complete
merged draft still requires numeric/source validation and independent review.
An interrupted proposal with only a capacity defect can be retained for this
correction without inheriting a verdict. The quotation limit is unchanged.
The source-integration and citation-capacity suite passed all 87 tests.

`scripts.run_live_checkpoint` is the explicit live entry point. It verifies
the original PDF hash, reads a provider-matched credential from the selected
environment file, uses `LLMGateway`, and retains the ordinary shared deadline.
It records progress, usage, a result JSON and Markdown in a new output folder.
It forbids the mock provider and never writes credentials to those artifacts.

## Second live continuation

After the citation-capacity fix, a second real `gpt-6-luna` continuation from
the first live checkpoint made 19 gateway calls and stopped in 377.368 seconds.
Reporting reused its saved selection and introduction. The strict briefing
context check required a fresh briefing; its independent reviewer rejected
missing interim assurance and a cash-flow interpretation that failed to
preserve the worsening operating loss before working-capital changes. It
therefore stopped at `executive_brief`, before source integration. Results
are retained under `output/live-589-20261112-02/` locally.

Neither live continuation reached the 900-second limit. Neither completed all
publication gates, and no approved PowerPoint was exported. The second run
did not reach the new reference-correction operation, so that specific live
behavior remains unverified. Its five focused offline tests, including reuse
of a saved over-capacity proposal followed by a fresh independent verdict,
passed. The current remaining failure is semantic briefing validation, not
proof of a successful report or a fresh-document latency guarantee.

## Exact briefing reuse and bounded citation choices

The lost briefing reuse was traced to section navigation links populated by
`link_coverage` after meaning review. Replacing only that derived bookkeeping
with its pre-link state reproduced the original full environment checksum;
document, observations, calculations, insight content and the presentation
otherwise matched. Checkpoint matching now recognizes the empty or exactly
derived navigation state. It still hashes all original sources, scope checks,
findings, requirements, assurance and plan content. Foreign navigation IDs and
changed facts, source text, source findings, scope or plan cannot gain reuse.

A third real continuation reused the approved briefing but showed that the
reference repair model could transcribe an overlong passage despite a prompt
requesting references. Repair schemas now enumerate premeasured source option
IDs. Python restores each chosen literal span; the model cannot return a new
passage or combine ranges in this response. Individually long source lines may
offer exact word-bounded slices, while the complete original line remains
available to the reviewer. All restored evidence still receives literal and
independent semantic checks.

The fourth real continuation passed supplementary-source review with the new
reference-choice operation, then the independent final reviewer rejected two
analysis pages for incomplete source qualifications. Its result is retained
under `output/live-589-20261112-04/`. The continuation took 137.750 seconds
and three real calls; this result remains partial, not an approved export.

Before final export validation, the worktree integrated existing GitHub main
commit `b792ce8`, retaining its source-bound local publication-copy corrections,
briefing recovery and native page-budget checks alongside these fixes.
The combined retained/source/checkpoint regression run passed 466 tests with
12 optional private-fixture skips.

## Local publication-copy recovery

Subsequent real continuations exercised main's source-bound local repair path.
They exposed a source-context mismatch: the publication reviewer received
adjacent original pages, but the local writer received only the anchor pages.
Both now receive adjacent original pages and layout. Eligible numeric rows
remain unchanged. Legacy anchor-only selection fingerprints can be recognized
for structural continuation; they do not grant publication approval. The final
review separately fingerprints the complete adjacent source layout, so a
changed neighbor revokes that review, and changed observations still reject
selection reuse.

Local edits can append missing source-supported qualifications without
retranscribing accepted sentences. The complete merged message retains its
2,000-character limit and ordinary literal-source and numeric checks. An
initial 500-character append-item limit rejected a multi-sentence model
paragraph; append items now share the existing full-message limit, with the
merged limit still enforced. Exact direction-token offsets are included in
contract feedback so a rejected adjective in a source-only driver is not
mistaken for a different supported comparison in the same clause.

The live runner also retains structured-response errors and local revision
proposals inside its ignored output directory for reproducible diagnosis.
These artifacts may contain document excerpts and are never committed.

## Status at the requested early commit

The eleventh real continuation stopped after 126.088 seconds and two calls.
The remaining contract failure is an attributive direction in the inventory
driver explanation; no final publication approval or verified PPTX exists yet.
The user requested committing and pushing this intermediate repair before
finishing the export. This is a reporting continuation, not a successful
fresh-document end-to-end benchmark.

All eleven private .589 request/recovery replay tests passed after integration.
Current main already supports the original literal day-count definition, so
the private recovery cases now explicitly inject an unbound amount into saved
copy while retaining the original source data and original valid copy for
the synthetic repair response. They test recovery only, never real approval.
The newly available full local suite is also running; it has reported failures
that remain to be diagnosed, so no full-suite success is claimed for this commit.

## Verified real-model continuation and PowerPoint export

The twelfth continuation passed final original-page review, completed all three
translation/review batches and reached a complete analysis in 232.612 seconds,
using ten real `gpt-6-luna` gateway calls. Its diagnostics are retained locally
under `output/live-589-20261112-12/`. Previous local-correction diagnostics now
reach the next writer as untrusted feedback, alongside the source review's
questions; they grant no approval or new numeric eligibility.

Its first export revealed a separate scope bug. Financial QA narrowed the
whole analysis message to the chart's annual series, discarding already-bound
interim periods explicitly compared in the same message. Direction checks
now retain literal source periods named by each individual text component.
An unqualified title still follows its displayed series, and cannot borrow
the message's scope. Unknown endpoints, cross-basis comparisons, reversals,
other entities/currencies and wrong directions retain their normal checks.
The original observations and reviewed prose are unchanged. The dedicated
direction/mixed-period/source-retry suite passed 32 tests.

Exporting that same complete analysis through the normal financial, native
preflight and rendered gates then succeeded in 28.894 seconds, with no new
model calls, no forced export, no visual repairs and no reported visual issues.
The editable deck contains 20 slides. All slides were also rendered with
installed Microsoft PowerPoint and visually inspected. Local outputs are in
`output/live-589-20261112-export-01/`; the PPTX SHA-256 is
`6f94bc6b75d5d09e364680f11a79d98c7133f067b21387cc8ce41dd84bfb1dfa`.

This verifies the original .589 checkpoint's real-model continuation through
successful export. It does not establish a fresh full-PDF latency guarantee.
The initial full-test failures were traced to Windows sandbox temp-path
length and blocked Streamlit loopback sockets; the complete suite was
restarted with short workspace temp paths, working loopback access and
repository-compatible pandas. An older unsupplied-page test now explicitly
withholds the page because neighboring pages are intentionally supplied by
default; its source rejection boundary is unchanged.

Final validation:

- The complete local Python run finished with 6,997 passes, 38 optional skips
  and six environment failures. Three failures came from missing `pytz` in
  the isolated pandas installation; three came from lazy tokenizer vocabulary
  initialization inside transport tests that intentionally forbid network
  access and clear the environment. After installing `pytz` and initializing
  the public tokenizer vocabulary before those tests, both affected test
  modules passed all 154 tests with the original network/leak mocks intact.
- All 104 final direction/source-retry regressions passed, including a case proving
  that explicitly named endpoints outside a chart retain their intermediate
  source observations, so a hidden reversal cannot become a continuous trend.
- All 19 notification/timer frontend tests passed.
- Direct comparison with .589 confirmed an unchanged original document,
  unchanged raw values/periods/units/evidence for all 1,521 observations and
  unchanged calculation results. ZIP integrity, 20 slides and six editable
  native charts were confirmed. The PowerPoint-rendered PNGs and visual review
  record remain local alongside the verified PPTX.
