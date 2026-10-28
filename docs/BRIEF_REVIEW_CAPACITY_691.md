# Briefing review capacity and checkpoints (.691)

This repair is separate from the five pre-existing, uncommitted briefing files.
Their original SHA-256 hashes are retained in a private manifest. Validation is
offline; no real provider request, commit or push is authorized for this work.

## Observed failure

The saved run lasted 1,485,080 ms. Ten `BriefMeaningReview` requests consumed
716,492 ms of provider latency; five were truncated. Audit navigation succeeded
on its first request. The final failure preceded export and localization.

The initial grouped review exhausted 16,384 and 24,576 tokens. A subsequent
single-item review completed, identified genuine qualifications needing repair,
and led to a source/copy correction. Reviewing the corrected five-item briefing
then exhausted both allowances on item index 2. The old collector threw away
the earlier complete outputs, skipped indices 3 and 4, and marked every pending
item with a cached generic review-unavailable error. That error was subsequently
sent to a meaning-copy repair even though no semantic verdict existed.

## Repair

- Group review retains its two original allowances. A single-item review has
  16,384 / 32,768 output tokens with identical complete input and provider-default
  reasoning. Only proven length truncation gets the larger request. A complete
  invalid response has at most one separate format correction.
- Each complete partition passes the existing evidence/reference, arithmetic,
  qualification and independent audience-direction gates before checkpointing.
  A truncated JSON fragment is never parsed or treated as partial approval.
- A failed item is recorded as unavailable; the remaining items are still
  checked. Exhausted capacity is a distinct private exception that bypasses
  source/meaning copy repair and salvage. The writer boundary exposes it as a
  retryable reporting failure, naming the unfinished item instead of condemning
  the whole briefing's meaning.
- One invocation cannot repeatedly retry an exhausted context. A new explicit
  reporting retry may reuse completed checks only with an exact fingerprint of
  candidate copy, evidence, whole-brief/shared context, document, profile,
  observations, calculations, topics, presentation plan, insights and assurance
  decisions. Changed context invalidates reuse. Genuine rejected meanings remain
  rejected, and no unavailable claim can certify the final briefing.
  Persistence is only for an unfinished review. A fully completed checkpoint
  never replaces a new independent review, and an older unresolved checkpoint
  cannot resurrect work already completed for the same context.
- A matching saved candidate can resume its unfinished checks before another
  draft/source selection. Source and topic coverage gates are checked again.
  Fresh report planning may invalidate this match; reuse is never assumed.
- Foreground progress identifies the item, request/capacity retry and completed
  checks. Background writers enqueue these messages; only the waiting caller
  invokes the UI callback. Detail changes keep the same stage clock and do not
  advance the workflow percentage artificially.

## Offline evidence

Private scripts under ignored `tmp/` replay the .691 candidate with scripted
responses and disabled network access. Before the repair, four requests visited
indices 0, 1 and 2 and stopped, leaving 3 and 4 untouched. After the repair, six
requests visit all five indices, preserve the four complete outputs and record
only index 2 as unavailable. Scripted outputs do not establish semantic approval
of the real PDF; separate synthetic tests exercise every downstream gate.

Regression tests cover checkpoint reuse/invalidation, no copy repair on capacity
failure, bounded retry, exact input preservation, source/arithmetic/direction
checks, background callback ownership and stage timing. Three legacy assertions
assumed a comparison-correction audit was the last warning. They now select that
explicit audit code, retaining the same semantic and request-count assertions.
Full regression also exposed an overly broad first implementation of checkpoint
reuse; it is now restricted to unfinished work. The original item-scoped evidence
and arithmetic regression remains unchanged and passes. The legacy format-failure
test now verifies a distinct unavailable exception, exactly one format correction,
no repeated calls in the same invocation, and no cached semantic approval.

The higher single-item allowance has not been validated against a real model.
It provides more bounded output capacity, not a guarantee of completion.

## Final validation results

- The final full offline suite ran in two disjoint file shards: 2,807 passed /
  9 skipped and 3,357 passed / 5 skipped, totaling **6,164 passed, 14 skipped,
  zero failures**. Four dependency/event-loop warnings remain.
- A separate HEAD-based snapshot, with only this repair overlaid and all five
  earlier briefing changes excluded, passed **102 targeted offline tests**.
- The corrected audit-record assertions and checkpoint boundaries passed a
  focused set of **63 tests** before the final complete rerun.
- External socket connections were blocked; loopback was permitted only for
  local test servers. All provider outputs used in reproduction were scripted.
- The original five files remained byte-identical, the staging area remained
  empty, and HEAD remained `8a2767aab4bc9292907ce674c0a950f00db50e63`.
  No real model, commit or push was run.

Private logs are in `tmp/691-verified-tests-0.log`,
`tmp/691-verified-tests-1.log` and `tmp/691-isolated-final-tests.log`.
