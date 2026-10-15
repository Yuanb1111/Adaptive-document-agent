# Bounded introduction recovery with current-draft review

The two affected v142 runs stopped at the foreground 73% checkpoint after an
independently running introduction failed. This checkpoint retained extracted
evidence and calculations while avoiding further editorial requests. The failure
was not a percentage-based timeout.

One run exhausted its meaning-repair output allowance entirely on reasoning,
before emitting JSON. The other completed a meaning correction, but its next
review introduced a material omitted-source objection and also described defects
already absent from the corrected meanings. A safe recovery must distinguish
transport capacity, binding to the actual current draft, and new source omissions.

## Capacity

Meaning revision uses a bounded 32,000-token request and one 40,000-token retry
only for a typed output-length truncation. Both requests retain the identical
complete source, original meaning inventory, ownership and instructions. No
partial JSON is accepted. Other schema, transport, privacy or cancellation
failures do not authorize that retry. Provider reasoning settings and independent
semantic review requirements remain unchanged.

Attempt audits are recorded before requesting a response, including failure
metadata and the complete exact-ID inventory. A valid response must still account
for every original meaning exactly once and preserve its owning source part.

## Current review and newly identified omissions

Independent review must identify the current selection snapshot and bind any
rejection to actual current meanings or their owning source evidence. Original
drafts used to check preservation are distinct from the current review targets.
An unbound or stale response does not approve or reject another snapshot; its
correction is bounded and must be a fresh independent review of the full source.
The single binding correction is shared across all semantic rounds. A correctly
bound rejection cannot use this path to obtain a different verdict without an
actual authorized draft correction.

A newly identified omitted-source requirement after meaning repair may receive
one bounded model correction and another independent review. Earlier selected,
repaired meanings remain protected. Python cannot invent inclusion decisions,
alter semantic verdicts, remove difficult claims or turn a rejection into an
acceptance. Persisted review validity must remain tied to the exact current
selection and source, including after serialization and edits.
Report and export validation return stale approvals as blocking validation errors
while preserving their error-list contract and any other collected failures.
There are at most three semantic rounds and four independent reviews in total,
including the optional binding correction. Newly required parts are authored by
the model from their literal source; the additive correction cannot replace or
drop any earlier selected decision or meaning.

## Replay integrity

The external checkpoints and their matching source PDF remain read-only. Recorded
provider artifacts, new protocol metadata, synthetic test responses and absent
historical responses must be labelled separately. Missing future model output
or independent approval remains a strict stopping boundary. Synthetic successful
flows test orchestration and native PPT construction; they do not establish
fresh semantic approval of the actual source document.

The five introduction-slide and twenty body-slide limits are unchanged, with
Data Index counted separately and analysis continuation pages included in the
body. No new setting, provider-specific workflow or extraction change is added.

## Validation

The recorded `.180` and `.068` failures were resumed through the real reporting
orchestrator with the actual PDF hash guard and retained-analysis validators.
The original checkpoints, PDF, observations and calculation results were
unchanged. The capacity case reached the missing retry-response boundary; the
current-draft case retained all twenty revised owner/meaning pairs and reached
the missing newly bound independent-review response. Both remained partial and
blocked PPT export, as required when those replies are absent.

A separate explicitly synthetic full reporting flow completed capacity retry,
meaning splitting, stale-binding correction, additive omission correction,
independent acceptance, coverage review and native PPT construction. Negative
flows covered exhausted capacity, repeated stale binding, rejected additions and
attempted changes to the protected inventory. No real provider request or fresh
semantic approval of the actual document is claimed by these tests.

Validation covered 811 distinct tests across 50 related files. The final broad
46-file run passed 757 tests and skipped four optional external-record cases;
all four were separately enabled and passed. Another 50 tests in four associated
summary/export files passed in focused runs, including the local-render export
preflight checks. The external cases comprise the two new failure checkpoints,
the prior reporting checkpoint, and the recorded capacity transport regression.
