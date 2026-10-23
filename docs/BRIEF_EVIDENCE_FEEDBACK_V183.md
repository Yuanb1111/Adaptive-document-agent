# Brief evidence repair and failure attribution (v183)

The recorded v182 failure ended before supplementary review: the executive brief
was absent after source and meaning correction failed. Reporting labelled this
as a stale supplementary review instead of retaining the original brief failure.

Three independent issues were reproduced without model calls:

- A claimed rule reference occurred on the cited page but in a preceding evidence
  block, not in the selected quote. The numeric gate correctly rejected it. The
  residual text-only correction could not restore that missing source quotation.
- A relative prior-year date followed several comparisons in one sentence. The
  date clarifier considered all earlier endpoints rather than the nearest one.
- A meaning patch applied a blanket audit label to the same period across source
  tables with different status bindings. The rejection was correct, but this
  source conflict did not receive the existing bounded contract feedback.

## Changes and boundaries

The existing residual source request may explicitly append evidence reference IDs
from the original catalog on that item's already cited pages. It cannot remove or
replace existing quotes, borrow another page, invent an ID, exceed four quotes or
override source checks. Python copies only the selected literal block. Source
validation and fresh independent meaning review remain mandatory. No extra source
request is added and no evidence is selected by deterministic claim heuristics.

Relative dates use the nearest complete endpoint within the current sentence or
semicolon-delimited clause. Numeric sentence endings now terminate that scope.
Prior-year aliases still require matching source columns; arbitrary years, new
counts, durations and amounts remain invalid.

A conflicting same-period status can use the existing shared two-request
format/contract budget. It is not accepted or resolved by Python. Feedback directs
the model to remove or narrow the unsupported assertion; complete source and
independent semantic checks run afterward. Entirely unsupported status assertions,
invented quantities and exhausted corrections retain the existing fail-closed path.

An unavailable final brief is now reported as `executive_brief / ExecutiveBrief`
with its original diagnostic, before entering supplementary source integration.
The reporting retry checkpoint remains available; no unreviewed brief is exported.

## Verification

The private incident replay confirms the original claim still fails without its
quote, an explicit same-page quotation passes the source gate, the permitted date
no longer triggers a new-year error, and the original conflicting audit patch is
still rejected but receives bounded corrective feedback. The replay does not
fabricate an independent review or claim a successful live-model rerun.

Synthetic regressions exercise reference ownership, duplicates, forged source
text, quote limits, date boundaries, conflict correction/rejection, fresh review,
and actual orchestrator failure attribution. Existing brief, assurance, source,
checkpoint and privacy suites remain required. v182 capacity and timing changes
are retained without lowering model reasoning or review quality requirements.
