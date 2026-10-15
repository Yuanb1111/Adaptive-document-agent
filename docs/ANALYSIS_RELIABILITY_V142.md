# Preserve inventory decisions and topic ownership during report recovery

The affected v141 checkpoint stopped during reporting. Its introduction source
was fully read, but the authored audience-decision inventory failed structural
validation before independent review. The invalid response was not retained,
so its exact missing, duplicate, unknown or all-omitted condition cannot be
reconstructed from that export. Separately, a cash-flow topic's unresolved
multi-step loss claim survived question fallback because an earlier correction
had changed the summary wording and recovery matched that wording literally.

## Introduction inventory

Inventory validation must retain the exact authored decisions and actionable
structural differences. One bounded model correction receives the complete
original source, the invalid inventory and its diagnostics. Python must not
choose inclusion, silently remove decisions or infer missing claims. Any corrected
inventory must meet the original exact coverage requirements and continue through
the independent source/importance review and complete meaning coverage checks.

## Topic ownership

Recovery must use the selected topic and its exact linked evidence to identify
summary copy after earlier validated corrections. A common value or a partial
overlap cannot establish ownership. Question fallback preserves the selected
topic, evidence and original rejected copy in diagnostics, and remains subject
to the existing claim, direction, source and no-new-errors gates.

## Replay scope

The checkpoint retains source pages, raw tables, observations, calculations,
topics and briefing artifacts. These can exercise reporting, planning and
recovery without a new provider request. Missing original provider replies or
never-performed independent reviews cannot be treated as recorded acceptances.
Tests must distinguish recorded replies, replayed validated artifacts, synthetic
protocol fault cases and unavailable mandatory responses. Synthetic positive
paths are integration checks, not fresh model approval of the actual source.

No document-specific workflow, extraction metadata change, relaxed validation
or new presentation setting is introduced. The fixed main-body limit remains
twenty slides, introduction at most five, Data Index separate and analytical
continuation pages included in the body count.

## Validation

Across forty test files, 612 distinct tests passed, including inventory repair,
source ownership, claim direction, topic recovery, reporting orchestration,
briefing lifecycle, native PowerPoint export and negative evidence cases. Both
production changes also received an independent cross-review.

The external checkpoint test is enabled with `ADA_REPORT_CHECKPOINT` and
`ADA_REPORT_SOURCE_PDF`. It was run with the affected checkpoint and its original
matching PDF. The test uses the real reporting retry entry point and gateway,
with offline transport adapters; production version, hash and state guards stay
active. Only the fixture copy adopts the new pipeline version because its
extraction-v19 and analysis-v74 evidence contracts are unchanged.

- All 1,537 observations, four calculation results and the saved two-item verified
  briefing were preserved. All five selected topics compiled with
  `planning_origin=topic_compilation`, without a fallback plan. Separate full-topic
  compilation passed the strict claim and presentation validators.
- The complete introduction reading was replayed from retained responses. A
  clearly synthetic 63-to-64 decision inventory fault and correction exercised
  the new protocol against the actual complete source; it is not a reconstruction
  of the missing historical invalid response.
- The unavailable historical independent introduction verdict remained a hard
  boundary. The replay returned a partial reporting checkpoint and prevented
  native PowerPoint construction. It did not invent an acceptance.
- Separate fully synthetic success and rejection tests ran the full reporting
  orchestration. The accepted fixture passed independent introduction and visible
  meaning coverage checks before native PowerPoint construction; the rejected
  fixture retained partial results and blocked construction.
- The original checkpoint bytes and model were unchanged. No fresh model API
  request was made. Provider-response, validated-artifact, synthetic-protocol and
  unavailable-response provenance are distinct in the replay adapter.

This verifies reporting wiring and strict failure boundaries; it does not certify
a fresh model's semantic acceptance of the actual document's introduction.
