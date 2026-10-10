# Candidate scoring output-limit recovery (v109)

The default live run stopped at 66% in the planner operation
`SemanticCandidateScores`, reporting output-limit truncation at 65,536 tokens.
The existing evidence prefilter bounded review to 160 candidates, but scoring
still requested every decision and explanation in one model response. This
failure precedes company-introduction and PowerPoint generation.

## Behavior

Each scoring request now returns decisions for at most 40 candidates. Every
request still receives the complete losslessly encoded reviewed candidate set
and document profile as comparison context. Instructions require consistent
utility criteria and global redundancy assessment; context-only candidates are
not eligible decisions for the current batch. Python ranks the combined reviewed
set once, using the existing evidence gates and final top-candidate cutoff.

Only a gateway-reported structured-output error with `finish_reason=length`
triggers subdivision. The failed batch is regenerated from its original inputs
in two smaller batches, with at most three subdivision levels. Successfully
completed responses are retained; gateway cache reuse also avoids repeating them
when a later attempt fails. Partial JSON is never parsed, completed or accepted.
An exhausted recovery still raises the original visible truncation error.

Privacy and transport failures propagate immediately, without another endpoint
or model. Non-length schema errors retain the existing bounded gateway behavior.
All model requests continue through `LLMGateway`, and provider reasoning policy
is unchanged.

Rationale IDs belong to their original response batch. Repeated short IDs across
different batches do not share their meanings or rewrite the original references.
Duplicate IDs within a batch, ambiguous decisions, missing decisions and
context-only returned decisions remain auditable and fail closed. The response
audit records original successful batches and failed truncation attempts with
their requested IDs and reported output tokens. Old JSON remains readable.

## Local validation

Synthetic gateway tests cover:

- complete batch coverage, unchanged global ranking and preserved source fields;
- the reported 65,536-token truncation, splitting only the failed batch;
- cache reuse of completed requests and JSON audit round trips;
- batch-specific meanings for identical rationale IDs;
- rejection of a context-only decision returned in the wrong batch;
- immediate propagation of privacy and transport failures;
- bounded, visible failure when every smaller batch remains truncated.

Private local replay uses stored analysis 88 and 89. Their 1,048 and 1,582
original candidates remain in the result, with the existing 160-candidate review
budget unchanged. Simulated truncation in the second batch produces attempt
sizes `40, 40, 20, 20, 40, 40`. Both replays preserve the original supplied
decisions, complete expanded explanations and global ranking under the same
input evidence. No live provider request or private-file upload is made.

The affected planner, scoring and reasoning-policy tests pass 208 cases.
The complete suite passes **3,299 cases**, with 8 skipped and no failures/errors.
After the final type annotations, the 43 affected scoring regressions pass again.
Fresh v109 default/custom runs remain necessary to measure live output quality,
cost and latency. Multiple requests repeat comparison context, so batching is a
reliability change rather than a claim of lower total token cost. It cannot
guarantee that a provider will complete even the smallest permitted batch.

`PIPELINE_VERSION` is `2026-10-10-bounded-candidate-scoring-v109`; analysis cache
version advances to v61. Extraction remains v11. Reload the deployed application
before retrying; a prompt change is not required for the default run.
