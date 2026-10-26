# Audit draft correction v198

The v197 diagnostic ending `.243` completed the introduction with five physical
slides. It failed later in `report_audit_scope` after roughly nine minutes.

The causal batch contained one monetary loss amount and two percentage-of-revenue
observations. Its first draft quoted only the six-character parenthesized values
for the percentage rows. Those quotations failed the existing eight-character
schema minimum. This is a real invalid response, not evidence of assurance.

The controller counted that format failure as `binding_validation` and spent the
batch's one binding correction. Its next draft repaired the quote length but
still proposed `unaudited` bindings for the percentage observations. The source
validator correctly rejected those bindings, but the already-spent counter
stopped the batch before the model received the specific disposition contracts.
An adjacent batch did receive those contracts and changed its ratio disposition
to unknown before entering independent review; it was cancelled when its peer
failed. The remaining cancelled batch is not an additional diagnosed failure.

## Change

- Count complete malformed writer output under `draft_output`, with one correction
  per batch, independently of `binding_validation` and `independent_review`.
- Keep the hard maximum of three draft attempts, including malformed attempts.
  Repeated failures cannot borrow another category's correction. Reviewer output
  repair, transport/capacity limits and independent acceptance remain unchanged.
- Supply retained target constraints on the first request and in schema feedback.
  The existing eligibility rules are reused; they are not new assurance decisions.
  Ratios, percentages and other ineligible measures must be explicitly proposed
  as unresolved with source-specific reasoning and independently reviewed.
- Keep exact schema field errors and the complete raw response in diagnostics.
  An exhausted draft-output error now identifies its actual field path and limit.
- Change the pipeline and request-capacity identities to v198. Previously completed
  source proofs remain subject to their existing full validation; extraction and
  analysis cache versions are unchanged.

Python does not change facts, flip assurance labels, synthesize unknown reasons,
select source meaning or accept a review. The model still supplies every corrected
draft, and fresh independent review is mandatory. Truncated/refused output and
transport/privacy errors cannot become format corrections or approvals.

## Validation

The audit and cache-contract regression selection passed 303 tests. Seven focused
v198 tests pass, including the real LLMGateway parsing path, both error orders,
repeated-error stopping, the three-draft ceiling, rejected unknowns, preserved
source data and terminal truncated output.

The complete local Windows suite then returned 5,819 passed, 14 skipped and two
failed legacy assertions in `test_report_format_recovery_v178.py`. Both asserted
the old shared format/binding budget or its old terminal exception type. Those
assertions now require the separate output counter, untouched binding/review
counts, bounded failure, exact diagnostic field and retained original exception.
The subsequent 43-test run covering that entire module and the output/binding/
review correction suites passed. Two additional focused gateway/truncation cases
were added after the full run had collected tests and passed in the focused runs.
The full suite was not repeated after these test-only updates. The prior local
Streamlit subprocess test passed with normal process permissions. Skips require
Linux rendering/font integration or explicitly supplied private checkpoints;
dependency event-loop warnings remain visible in the full-run log.

Syntax checks and `git diff --check` passed. This validation does not certify a
fresh live whole-document analysis or the Linux CI matrix for v198.

```text
python scripts/replay_audit_draft.py path/to/analysis.json
```

For `.243`, the replay uses its two actual recorded responses and unchanged full
source context. The third writer request now receives all ten binding diagnostics
and the two unresolved-only target contracts. The replay stops there because no
real third draft or independent review was recorded. No model is called, no new
answer is invented, and no semantic or end-to-end approval is claimed. Private
diagnostics are read in place and are not included in the repository.
