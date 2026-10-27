# v206: explicit merged-brief review addresses

The v205 export ending in `120633.573.json` passed audit qualification and
report generation, then failed supplementary-source integration. Its original
brief contained three items. The writer added two supported findings at merged
indices 3 and 4. The independent reviewer incorrectly treated index 4 as an
address into the three-item original brief and rejected the second addition.
The original writer correction had already been consumed by a missing quotation
for a reporting duration, so this reviewer misunderstanding ended the run.

The reviewer now receives a complete indexed merged-brief ledger. Every row
identifies its original/addition ownership, and every source disposition lists
its exact resolved addresses. The original brief, full source pages, selected
topics and proposed additions remain available. Instructions distinguish an
include binding into an addition from a covered binding into an original item.

Python builds this ledger only after the existing structural and literal-source
validation succeeds. It does not choose materiality, approve a binding, rewrite
a verdict or add retries. The independent reviewer still decides whether the
bound conclusion actually carries the source meaning. Failed candidates remain
unapplied, and accepted review fingerprints still expire when evidence, selected
topics or the final brief change.

## Validation

39 focused tests passed across source integration, completion/capacity recovery,
source finalization and fallback budgets. New cases reproduce three originals
plus two additions, verify exact index-4 content, retain semantic rejection,
and reject out-of-range, covered-addition and include-original addresses before
any independent approval request. Raw source pages and original items survive.

Real-model validation uses the user's explicit authorization for `.573` and
the same original PDF. Private checkpoints, model responses, cache and export
files remain in ignored local diagnostics and are not committed.

The `.573` continuation passed strict export in 129.9 seconds with 8 model
calls, producing 20 slides (19 body and one data-index page). Serialized output
passes the production completion gate; raw observations and source pages match
the original file exactly. Separately, replaying the unchanged previously
rejected two-addition draft to the real independent reviewer succeeded in one
call, confirming the exact index-4 case rather than relying on a different draft.

## Fresh orchestration finding

A separate run from the original PDF, without a checkpoint or pre-existing
cache, exposed an earlier introduction-resolution reference error. A disposition
referenced a meaning in another source part. Ownership validation correctly
rejected it, but that error type did not use the existing protocol-correction
budget. The exact references and allowed same-part addresses now return to the
model within that same one-correction budget, shared with unapplied-correction
errors. Cross-part references remain prohibited; no fuzzy rebinding or automatic
semantic approval is introduced. Full independent introduction review remains
mandatory after protocol validation.

Introduction regressions: 414 passed, one skipped for an external fixture.
New tests cover unknown, duplicate and cross-part references, immutable sources,
repeated failures and the shared correction budget.
The unchanged invalid resolution from that fresh-run checkpoint was also
replayed: one real-model correction passed the same ownership validator while
retaining `semantic_approval=false`. This protocol replay does not substitute
for the mandatory independent introduction review or a complete pipeline run.

## Completed fresh PDF-to-export verification

After the introduction-reference fix, a second run called the public
`DocumentOrchestrator.analyse_pdf()` entry point with the original PDF, no resume
checkpoint, a previously absent disk cache and response caching disabled. It
used the configured `deepseek-flash` model and the same 20/5/10 body/introduction/
analysis slide caps. It completed discovery, fresh extraction, analysis,
introduction verification, audit qualifications, physical-budget refinement,
briefing, supplementary-source integration, localization and strict export.

Measured result: **1213.4 seconds, 124 physical model calls, 21 total slides:
20 body slides and one data-index slide**. Reloading the result JSON passes the
production completion gate and the saved PPTX passes the exported-budget check.
Rendered QA reports `passed`, `facts_preserved=true`, zero errors and zero
warnings. The input PDF hash is unchanged. No force flag, mocked approval or
manually completed pipeline state was used. This verifies this full run; it is
not a guarantee that future stochastic model outputs cannot fail validation.
