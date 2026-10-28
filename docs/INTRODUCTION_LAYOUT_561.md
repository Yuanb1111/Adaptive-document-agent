# Introduction layout failure .561

The saved October 28 `.561` result fails at `introduction_editorial`, with an
incomplete introduction review and a five-physical-slide introduction budget.
It is a verified layout overflow, not an analysis deadline or response-capacity
failure. The introduction took 126.959 seconds: source reading 45.912s,
audience selection/review 53.508s, and editorial processing about 25.388s.
The log's pipeline version alone does not identify its exact Git commit.

## Reproduction and cause

The selected inventory has eight source parts and 24 mandatory meanings.
The initial draft contains 14 paragraphs, 4,179 body characters and five
logical groups. Native pagination needs seven physical slides. The first
layout response merges paragraphs, leaving nine paragraphs and 4,151 body
characters, requiring six physical slides. The second response is exactly
identical to the first revised draft. Both responses finish normally with
`finish_reason=stop`, not truncation; both use the configured reduced-reasoning
policy. That setting is observed evidence, not proof of why the model copied
the previous draft.

The remaining spill is the opening group. Its two paragraphs measure 5.352
inches against 4.357 inches of usable height. Even a concatenated single
paragraph would require 4.699 inches. Existing final choices only combine
paragraphs **within** their current groups, so no offered combination meets
five pages. The controller then spends its final existing correction on
another unrestricted full rewrite, which repeats the over-budget draft.
The cap correctly stops delivery.

## Fix

When the final selected-audience correction remains over budget and has no
feasible within-group choice, enumerate a bounded set of complete-paragraph
transfers from an overflowing body group to another existing body group.
At most 48 candidate transfers are probed and eight feasible choices exposed.
The enumeration changes no caller data and measures native pagination through
the existing expansion/packing code. It does not infer semantic similarity.

The model owns the choice and any faithful title changes. The supported
opening paragraph stays in place. A chosen transfer retains every paragraph,
label, word, display hint, fact ID and exact meaning reference. It can neither
delete a group nor move content to an appendix. The model can reject every
option and use the same response for a full source-bound replacement or
refuse. No extra correction round is added. If there is no measured option,
the existing full-rewrite path remains available.

All revised titles and physical pages are remeasured. Unknown selections,
mixed transfer/replacement edits, identity edits, missing meanings and unknown
facts still fail. Successful geometry still enters a fresh complete independent
source/meaning review; grouping compatibility and title meaning are not
mechanically approved. The new `SummaryLayoutAllocation` operation uses
LLMGateway and the existing default policy for unlisted operations, matching
the existing semantic-choice approach; no provider SDK or policy bypass is
introduced. The two-correction bound and analysis deadline remain unchanged.

## Offline evidence

```powershell
python -m scripts.replay_summary_layout "path/to/analysis_data.json"
python -m scripts.replay_summary_allocation "path/to/analysis_data.json"
```

The first command reproduces **7 → 6 → 6** pages with no feasible within-group
menu. The second replays the saved first rewrite and a **mock** transfer choice:
**7 → 6 → 5** pages; native PowerPoint generation also produces five. The only
measured transfer in this fixture moves the second paragraph of group zero to
the end of group four. Finding a geometric fit is not a recommendation that
these subjects belong under the existing heading: the real selector and
independent reviewer must decide coherence and appropriate titles.

The mock replay verifies the multiset of complete paragraph JSON records is
unchanged, including all fact/meaning bindings, and that all text appears in
native output. Local enumeration took about 1.18 seconds. This is a geometric
and controller regression, **not** real-model acceptance or full-report export
verification. The scripts do not write the supplied diagnostic or call a real
model; the new replay blocks socket connections.

Focused regressions: **69 passed**. They cover refusal, changed-title overflow,
unsupported fields, source-preservation failures in a replacement, bounded
search, cancellation, Local Only gateway routing and mandatory fresh review.
The unrelated five uncommitted summary changes remain untouched.

Full offline regression: **6,203 passed, 14 skipped** (3,352/10 and 2,851/4
across two file shards), with four pre-existing Windows event-loop cleanup
warnings. Outbound connections were blocked by the runner; loopback test
transports were allowed. Logs: `tmp/561-targeted-4.log`,
`tmp/561-full-0.log`, `tmp/561-full-1.log`, and `tmp/561-final-replay.log`.
No real model, commit or push was performed for this fix.
