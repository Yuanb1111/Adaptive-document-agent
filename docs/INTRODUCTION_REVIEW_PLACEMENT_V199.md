# Introduction review placement v199

The v198 diagnostic ending `.339` failed in introduction editorial selection
after approximately three minutes. Both independent review responses identified
the same omitted source part as `included_part`, although their selection digest
matched the current draft. Both also requested `repair_scope=meanings`. The
existing validator rejected the contradictory placement twice and exhausted the
single binding re-review before substantive correction could start.

The source part concerned material qualifications. Other findings concerned
currently included copy. The first response contained five findings and the
second four. This is a review protocol failure; it does not establish that the
draft itself was acceptable or that all proposed semantic criticisms were valid.

## Change

- Derive a part-level finding's current placement from its exact source part ID
  and the unchanged selection ledger. Current placement is already known data;
  it is not the reviewer's proposed action after correction.
- Require a rejected review, the exact current selection digest, unique source
  and decision ownership, empty meaning-reference fields and a literal quotation
  from the owning source. Existing canonical source binding happens first.
- Route findings on omitted parts to selection correction. Mixed findings use
  the existing meaning-resolution controller, retaining every finding.
- Keep the original model response and record each derived placement and routing
  change. Preserve reasons, issue types, source identity, decision values and the
  rejection. Python neither includes a part nor writes or approves slide copy.
- Leave stale digests, unknown/ambiguous ownership, invalid meaning references,
  foreign quotations and accepted reviews with findings to existing validation.
  Correction budgets and mandatory fresh independent review are unchanged.

The pipeline version is `2026-10-26-introduction-review-placement-v199`.
Extraction and analysis cache identities are unchanged.

## Validation

The initial focused selection passed 78 tests, including 16 new cases. The new
cases cover both tag directions, omitted-part routing, invalid ownership and
evidence, unchanged raw responses and source data, and the full mixed-repair
controller with subsequent accepted, rejected, unavailable and stale reviews.

The complete Windows regression run exited successfully: 5,839 passed and 14
skipped (5,853 collected). Skips require opt-in Linux rendering/font integration
or external private checkpoints. Existing dependency event-loop warnings remain
visible in the test log. Python syntax checks and `git diff --check` also pass.
This does not certify the Linux CI matrix or a fresh live whole-document run.

```text
python scripts/replay_introduction_placement.py path/to/analysis.json
```

The private `.339` replay uses each original rejected response and reconstructs
its recorded selection before canonical source binding. Assertions verify that
the resulting canonical decisions and review digest match the saved candidate.
Both responses now reach a fresh mixed semantic correction request, preserving
all five/four findings and original source parts. Neither needs a binding retry.
The replay stops before that unrecorded model response: it makes no provider
calls, invents no semantic correction and proves no end-to-end acceptance.
Private input is read in place and is not committed.
