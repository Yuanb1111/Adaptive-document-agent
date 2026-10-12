# Complete thematic introductions (v118)

## Observed failures

Standard export `.485` and customized export `.513` used the same 524-page
PDF with Summary on physical pages 10–21. The standard run read 128 parts,
including 63 substantive parts, then failed both five-page editorial attempts:
missing content, over-capacity pages and unsupported numeric paraphrases.
The customized run failed earlier on nested substantive spans on page 16,
where lines 10–12 belonged to two parts. These are distinct failures, not
evidence of a Streamlit process restart.

## Changes

- Permit one bounded model re-read of overlapping source ranges. Expand to
  whole intersected parts, including transitive intersections; retain accepted
  parts outside the repair scope. Unknown blocks and outside endpoints remain
  invalid. Exact ownership and source validation still apply to the replacement.
- Replace the implicit global five-page cap with a source-selected theme plan.
  The model assigns every substantive part exactly once, with at most twelve
  parts per theme. Missing, duplicate and unknown IDs get one bounded repair.
- Write and independently review each theme against its complete source facts.
  The first theme must explain the actual business/subject and scope. Subsequent
  themes cannot invent another issuer identity. Every part must contribute real
  meaning, not merely an attached ID. Numeric and literal evidence checks remain.
- Pack whole authored paragraphs to fit the native slide geometry without
  truncating or rewriting claims. Merge only exactly identical reviewed labels
  and copy, preserving all accepted source bindings. Retain per-theme review
  records and bind the merged output to its exact digest.
- Keep explicit legacy page budgets enforceable; the default introduction has
  no arbitrary five-page limit. This is not permission to omit source parts.
- Use at most two independent theme writers, further limited by gateway
  admission and Local Only serial execution. Long readings go directly to
  themes rather than spending two full-draft retries first. Corrections include
  the rejected draft and exact missing parts. No measured hosted speedup is
  claimed before an actual run.

All model access remains through the gateway. No provider SDK, new endpoint,
document-type workflow or source-specific semantic rule is introduced.
Financial table appendix and publication checks remain mandatory.

## Validation

Focused coverage includes adaptive pagination beyond five pages, explicit budget
failure, complete native PPT bindings after serialization, independent meaning
and business-opening rejection, outline ownership, privacy and cancellation,
and targeted overlap correction. Hosted verification uses the original PDF
whose SHA-256 matches both supplied exports; credentials remain in the browser.

Local regression: 1,072 core tests passed, five existing tests skipped (93.86s);
nine Streamlit startup/flow tests passed (16.23s). The latter run required the
established unsandboxed Windows socketpair workaround. These tests use mock
providers and do not establish hosted generation success.
