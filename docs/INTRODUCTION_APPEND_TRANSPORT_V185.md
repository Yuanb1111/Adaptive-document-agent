# Introduction append transport (v185)

The saved v184 run failed during company-introduction verification. The reviewer
identified a missing qualification at the included-part level, which authorizes
additions but not rewriting protected current assertions. The resolution model
returned one existing meaning verbatim followed by two new assertions inside an
`edits` entry. Its current meaning ID existed, was unique and belonged to the right
source part. The validator nevertheless rejected the multi-item replacement as
an unowned edit, and the pipeline correctly stopped before export.

## Change

The resolution validator now recognizes this strictly append-only transport:

- The meaning ID must exist, be unique and refer to a protected current assertion.
- Its exact source part must have an `included_part` finding. A meaning-level
  finding elsewhere in that part does not authorize this conversion.
- The first proposed assertion must match the original text exactly, with an
  empty or exact original source quotation. Later items cannot repeat that text.
- The original assertion and evidence remain at their original position. Only
  the additional model-authored items become additions at the end of the same part.
- All existing disposition/ownership checks still apply. Mixed explicit and
  transported additions to the same part remain invalid, as do arbitrary rewrites,
  unknown/duplicate IDs, foreign owners, missing findings or false dispositions.

The raw model response is retained. A successful protocol check records
`append_only_edits`, including its original meaning ID, owning part, addition count
and preservation result. The full revised union and normalization record reach the
fresh independent review. This is transport normalization, never semantic approval:
Python does not invent wording, select importance or assert that a new claim is
supported. The original source, normal source binding and fresh model review remain
required. The prompt still asks the model to use explicit `additions` directly.

No additional model request, provider coupling, reasoning reduction or retry is
introduced. The pipeline version identifies the new behavior; extraction and
unrelated analysis cache versions remain unchanged. The v184 coverage merge fix
is retained.

## Verification

The saved incident passes `scripts.replay_meaning_resolution` offline with zero
model requests, one unchanged original assertion preserved and two owned additions.
The original file and raw reply are unchanged, and `semantic_approval` stays false.
Synthetic tests compare the transport with canonical explicit additions and cover
ownership, immutable wording/evidence, malformed IDs, duplicate proposals and
disposition requirements. Full selection-flow tests require a new independent
verdict and prove both acceptance and rejection paths.
The focused introduction, source-binding, failure/retry, v184 coverage and gateway
regression selection passed all 282 tests.

The live-provider continuation and complete PowerPoint export have not been run.
Restart with v185 and retry reporting to run the remaining independent review,
reporting and export checks. An offline protocol replay is not proof of completed
semantic review or successful PowerPoint generation.
