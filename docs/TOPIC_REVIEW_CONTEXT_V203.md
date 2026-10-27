# v203: recoverable topic review and explicit analytical gaps

## Problem

A complete PDF extraction and successful PowerPoint render do not establish a
complete analysis. A truncated topic review previously discarded the question
plan and allowed an evidence-only fallback to pass completion. Separately, one
global explanation-reading allowance was divided across every calculation,
leaving large runs with a table window and little narrative context. Individually
supported summary statements could omit a material qualification elsewhere in
the available source context.

## Contracts

- Topic evidence review sends at most three complete topics per batch. Proven
  `finish_reason=length` failures retry the identical full request at 16,384 then
  24,576 output tokens. Exhausted batches split only between whole topics. The
  full invocation, including semantic corrections, has a 24-call physical limit.
- Partial JSON never becomes a verdict. A missing verdict is recorded separately
  from an explicit unsupported verdict. Successful siblings survive. Privacy
  violations and cancellation propagate; neither permits fallback or cloud use.
- Coverage and brief meaning reviews use bounded capacity recovery too. Physical
  retries consume the existing coverage call budget. Transport failures and
  exhausted capacity cannot trigger an additional semantic-format repair loop.
  Coverage merge recovery preserves its absolute 32,768-token ceiling.
- Unfinished topic review blocks completion and final PowerPoint export. The UI
  names unverified questions and unfinished coverage decisions, including their
  source metric labels and periods. Retained JSON remains downloadable. A later
  review clears historical gaps only through an exact accepted binding or a
  current complete coverage review with independently checked current topics.
- Each calculation retains a bounded reading allowance within the existing
  bounded request batching. Nearby and remote candidates retain literal text,
  source page and character offsets. Equal keyword matches prefer prose density
  over the raw number of letters in table labels. Retrieval is not a causal or
  importance decision.
- Brief writing receives bounded nearby companion passages sharing source metric
  labels. Independent meaning review sees the available source blocks and the
  whole current briefing, so it can identify misleading omissions: complementary
  outcomes, later comparable periods, different definitions, related totals,
  reconciliations, scenario conditions and source-attributed explanations. These
  are semantic relationships, not an industry or document-type checklist. A
  changed companion finding invalidates the whole-brief contextual approval.
- Existing literal source explanations may be attached to their exact displayed
  task inputs on a question-led analysis page. Both the live source quote and
  the insight evidence must bind. The normal numerical, provenance and page-plan
  gates still apply. A shared metric name or page number is not a link.

All semantic requests still pass through `LLMGateway`. Python binds references,
checks scope, calculates values and enforces budgets; it does not invent missing
measures or choose analytical importance. Original observations remain intact.

## Verification

`test_topic_review_recovery_v203.py` exercises real gateway parsing with injected
length failures, unchanged retry contexts, whole-topic splitting, partial success,
visible gaps, stale approval invalidation, call-budget accounting and propagation
of privacy/cancellation errors.

`test_report_context_v203.py` covers operational, survey and financial structures:
recent-period and counterpoint retention through compilation, incompatible-period
separation, companion qualifications, contextual omission review, whole-brief
memo invalidation, many-result retrieval and exact-input explanation attachment.
The semantic responses in these tests are controlled fixtures, not live-model
quality evaluations.

`scripts/replay_review_capacity.py` accepts arbitrary saved analysis JSON paths.
It injects transport truncation without contacting a model, checks unchanged
complete source payloads, reports stale references explicitly, and verifies that
the private input file is unchanged. Its output always states that it provides
no semantic certification. Local replay covered two distinct documents with
seven and three retained topics; both recovered their complete topic payloads.
Additional incomplete and older snapshots reported missing/stale topics instead
of inventing replacement bindings.

The saved PPT89 revenue case also confirmed that the previously missed narrative
passage is present in the new literal reading context. This establishes retrieval
coverage, not a new model-authored conclusion or an end-to-end regenerated deck.

Final local regression run on 2026-10-27: **5,914 passed, 14 skipped, 4 warnings**.
Skipped checks require external checkpoint fixtures or a configured real/Linux
renderer. Warnings concerned provider-test asyncio deprecation and Windows
event-loop cleanup. Streamlit tests
ran with local loopback access and a fresh workspace temporary directory.

## Remaining acceptance work

Run fresh end-to-end analyses through the configured model on multiple inputs and
inspect the resulting pages. Offline tests cannot guarantee semantic quality or
provider availability. Bounded recovery may still exhaust capacity; such a run
must remain visibly incomplete rather than becoming successful because export
would be possible. Source reading is bounded and does not promise an exhaustive
review of every PDF paragraph.
