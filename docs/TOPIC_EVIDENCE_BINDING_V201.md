# Topic evidence binding v201

## Observed run and artifact audit

The private `.288` analysis was a v200 run marked complete after 815,931 ms.
PPT88 contains 20 physical slides: 18 body slides and 2 Data Index slides.
Its five introduction slides and eight analysis slides meet the requested
section budgets. Completion did not establish that the intended story survived:
the selected topic plan failed and the exported plan used a fallback, with no
retained topic themes.

The saved topic selection contains valid catalog IDs with incorrect meanings:

- Annual and interim "loss" topics selected selling/distribution expense rows.
- "Gross profit margin" topics selected cost-of-sales percentage rows.
- The research/development topic selected other-income-and-gains rows and shares.

These are selection/binding errors, not changes to the raw extracted cells.
The existing structural checks confirmed the IDs existed but did not establish
that the authored topic actually described those IDs.

Cash-flow compilation also failed when duplicate disclosures had different
source labels/contexts. Annual duplicates have an existing common canonical
mapping and matching values/scope. Some interim duplicates differ in assurance
metadata and must remain separately selectable, rather than being treated as
interchangeable merely because their numerical cells match.

Read-only PPT checks found all 27 chart points across 10 charts consistent with
the page-owned exported observations, including signs and periods. This checks
the PPT against its analysis/export trace; it is not a new PDF extraction audit.
All 20 slides were locally rendered and visually inspected. No obvious major
overflow was found. Dense introduction text, sparse technology slides and the
fallback's loss of analytical topics remain quality limitations of that artifact.

Six calculations were blocked for conflicting values or incompatible
entity/reporting scopes. Their safety gates are retained.

## Agent changes

`topic_evidence_review.py` adds independent semantic checking of every selected
topic against its own complete source rows. The request shows literal metric
names beside IDs, raw and normalized values, periods, units, entity, categories,
definitions, assurance status and page evidence. All calls use `LLMGateway`.

The reviewer decides meaning. For rejected topics, one model correction may
choose known catalog IDs or revise the question to the actual evidence. The
correction catalog is a retrieval aid, never sufficient acceptance evidence.
Every revision receives a fresh independent review containing all newly chosen
rows. Python checks decision ownership, known IDs, unchanged siblings, numeric
and period constraints. It never chooses a replacement by metric-name matching
or by similarity of numerical trends. Failed revisions are withheld and audited.

Initial binding review precedes coverage review, so its omission ledger refers
to the corrected evidence. If coverage synthesis changes topic wording, a final
review checks the new draft without another correction loop. Unchanged bindings
are reused; changed drafts/facts cannot inherit an old acceptance. Budget and
takeaway revisions likewise require current review. Versioned historical
checkpoints cannot silently recompile unreviewed topics.

Requests have a 160,000-character cap and bounded output. Full evidence is not
sampled to fit. Initial review/correction/review has at most three calls; the
post-coverage check adds one only when its bound draft changed. Oversized or
failed reviews remain explicit failures, not fabricated acceptances.

Catalog compression now keeps metric names literal beside selectable IDs.
Other repeated metadata can still use lossless dictionaries.

`presentation_evidence_alignment.py` uses existing qualified semantic mappings
when recognizing repeated disclosures. Alignment still requires every selected
point to match in value, period, unit/scale, currency, entity, parent section,
categories, definition and assurance status. Source qualifiers cannot be erased
by a broad canonical label. Only presentation references change; raw observations
and evidence remain intact. The directional validator's strict gates are unchanged.

`presentation_source_series.py` exposes complete source-context views when
overlapping disclosures disagree in scope or value. The model chooses among
them. Python neither ranks a preferred source nor combines incompatible cells.
Changed catalog IDs require fresh topic selection rather than guessed rebinding.

## Verification and limits

New synthetic regressions cover operational metrics, wrong-but-valid IDs,
rejected corrections, unchanged siblings, Local Only routing, missing/duplicate
review decisions, stale evidence, catalog identities, strict duplicate alignment,
and independently selectable assurance scopes.

- Full local suite: **5,878 passed, 14 skipped, 4 warnings** (540.56 seconds).
- Final focused verification: **126 passed, 3 skipped**, including the final
  request validation and source-alignment checks.
- `git diff --check`: clean.

The warnings are Windows asyncio cleanup/dependency warnings; they did not
fail tests. No live provider run or new GitHub CI run was performed for v201.

The old structural/coverage unit tests explicitly isolate the new semantic
stage; new selector integration and full reporting fixtures exercise the real
gateway/schema boundary. No recorded historical model acceptance is invented.

`scripts/replay_topic_evidence_review.py PATH_TO_ANALYSIS_JSON` stops at the next
required model request. For `.288`, revised source choices invalidate two
old series handles: the replay reaches fresh selection with all 973 current
catalog entries, without making a model call or modifying the input. It does
not assert that a new end-to-end report has passed.

The pipeline version is `2026-10-26-topic-evidence-binding-v201`. Extraction and
analysis cache contracts are unchanged. The private inputs, rendered images and
local diagnostic logs are not repository fixtures. No issuer-specific workflow,
metric substitution, hard-coded document page or private observation ID is used
in the implementation.
