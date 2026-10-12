# Candidate scoring output truncation (v113)

The standard and customized hosted runs both stopped at 67%, reporting
`planner / SemanticCandidateScores / deepseek-flash / output tokens: 6000`.
This is explicit model-output truncation. The screenshots do not establish the
cause of an earlier apparent service reboot or identify the final batch size.

The scoring code allowed three splits of a 40-candidate batch: 40, 20, 10, 5.
At five candidates it propagated a further length failure despite smaller
complete-candidate batches being possible. Every request also used a 6,000-token
output ceiling.

## Change

- Raise this operation's ceiling to 12,000 tokens; this is a maximum, not a
  requested minimum response length.
- Bisect only a batch whose response explicitly finishes with `length`, down
  to a singleton. Each split strictly decreases the batch size, bounding a fully
  explored batch tree at `2*n-1` requests. A singleton length failure remains
  visible, identifies the candidate and split depth, and stops recovery.
- Retain all candidates as global comparison context on every request, including
  rejected decisions, source qualifications, observation membership and IDs.
  Ask for only current-batch rationale catalog entries and avoid echoing the
  already supplied source inventory.
- Attach a stable batch ID and recovery depth to gateway usage records. These
  locators are not document instructions or provider request fields.
- Preserve gateway caching of completed child requests. A later retry still
  reissues failed parents (they have no successful response cache); completed
  children can be cache hits while the same session cache remains available.
- Never accept truncated JSON, invoke format repair for a length failure, switch
  providers, or fabricate missing scores. Existing privacy and transport failure
  handling applies unchanged.

Pipeline marker: `2026-10-12-candidate-scoring-truncation-recovery-v113`.
Extraction and analysis schema versions remain unchanged. The scoring prompt
and output-policy field already invalidate the affected model-request cache
without invalidating unrelated successful model requests.

## Verification

Regression tests use the real LiteLLM adapter and gateway with mocked transport,
for both standard/customized profiles and cloud/Local Only routing. They force
every multi-candidate response to truncate, including syntactically valid JSON,
and prove recovery beyond the former three-split limit. Every source candidate,
raw decision and qualification survives; results match an untruncated baseline.
Usage records retain failed attempts, and repeated calls reuse successful
singletons. A permanently failing singleton and non-length errors stay visible.

Validation: 303 scoring, gateway, provider-policy, usage, planner, pipeline and
Streamlit retry regression tests passed (one pytest plugin pre-import warning).

No new hosted generation or paid model request is part of this local validation.
After deployment, confirm the v113 marker and rerun the two groups sequentially.
