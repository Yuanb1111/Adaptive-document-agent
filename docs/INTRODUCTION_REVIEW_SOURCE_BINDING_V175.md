# v175 introduction review source binding

The saved `analysis.680` run stopped before semantic repair because the independent
reviewer joined two nonadjacent sentences into a single `source_quote`. Its one
binding re-review repeated the same omission. The literal-source validator
correctly rejected both responses; whitespace normalization cannot restore missing
source words.

Review findings now reference their exact owning source part by `part_id` and leave
`source_quote` empty. Python copies the complete original passage into a separate
verdict before validation. The audit retains `raw_review`, the materialized `review`,
and per-finding source-binding records. Source text, page provenance, current
meaning IDs/text, reasons, finding kinds, repair scope and semantic verdict remain
unchanged. Copying evidence does not approve a finding or the introduction.

Nonempty model quotations still require a continuous literal match. Unknown or
ambiguous source references cannot be materialized. Wrong owners, stale meanings,
wrong selection digests and inconsistent acceptance/findings still fail the
existing checks, with at most one shared binding re-review. Recheck feedback now
identifies the returned quotation and its exact source reference.

A bound rejection proceeds to the existing semantic repair and fresh independent
review. Continued semantic rejection still blocks completion. Historical failed
audits are not rewritten or retroactively accepted. Tests use synthetic sources
and mock reviewers; no provider request or confidential source fixture is needed.

`PIPELINE_VERSION` is bumped to
`2026-10-23-introduction-review-source-binding-v175` so presentation and completed
result caches cannot reuse the previous contract. Extraction and analysis versions
are unchanged. The source-reference output schema and prompt also change gateway
request cache identity. Local Only routing remains entirely through `LLMGateway`.
