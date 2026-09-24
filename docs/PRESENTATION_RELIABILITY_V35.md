# Evidence-bound presentation repairs (v35)

## Root causes

- Percentage-labelled gross profit was not recognized as gross margin. A
  neighbouring cost metric could incorrectly acquire its directional word.
- Summaries linked to insights could fall back to all observations instead of
  following the insight's calculation inputs. Duplicate source contexts then
  looked like incompatible time ranges.
- Numeric validation did not follow that same input chain, so a correctly
  referenced ISO date could introduce unsupported month tokens during repair.
- Percentage units retained in table headers were not reflected in the allowed
  numeric spellings used by presentation validation.

## Changes

Claim validation, repair, cross-slide checks and numeric checks now share exact
insight-to-task-to-observation provenance. Repairs are revalidated and rolled
back per slide if they introduce new claim errors. Read-only QA works on a copy.
Repeated cross-slide reports of the same contradiction are deduplicated.

Summary bullets may additionally carry independent observation IDs. Annual and
interim statements about the same metric are checked separately, and proven
duplicate-reference alignment updates these bindings together with slide IDs.

Topic recovery prefers the model's evidence-bound takeaways in model-selected
order. Complete evidence sets must fit the reference budget; series are not
truncated to fill the summary. Where takeaways are unavailable, distinct-topic
insights are preferred over several insights about one topic. Repaired summary
bullets are rendered instead of reverting to old insight prose. Original prose
remains in notes.

Verified introductions also receive concise covers, ranking prompts require
dates/bases/attribution, and positive charts reserve space for data labels.
The cache/build identifiers are advanced to v35.

## Verification boundaries

Generic synthetic regressions cover multi-metric direction binding, repeated
repairs, exact source linkage, dates, percentages, read-only QA, summary topic
coverage and rendering of repaired text. Downloaded analyses 19 and 20 are
offline replay inputs, not committed fixtures. No external model is called by
these replays. Fresh model-generated introductions and editorial choices still
need an end-to-end run; offline export success is not a guarantee of their
semantic quality. This change does not merge ambiguous duplicate source rows
or fabricate a concluding recommendation.
