# Final claim revalidation (v163)

The v162 run ending `.882` completed analysis but its first PowerPoint export
reported a `directional_contradiction` on the executive summary's annual loss
comparison. The saved plan already contained coherent references and passed a
fresh read-only audit. Its embedded export diagnostics described an intermediate
plan, rather than the plan left after all repairs.

Two mechanisms combined:

- Equal-coverage duplicate series were aligned only when exactly one candidate
  remained. With three or more exact copies, one pass could remove a duplicate
  while leaving another ambiguous until a later pass.
- Comprehensive QA collected directional errors before the cross-slide stage.
  That stage could finish aligning summary evidence, but the earlier errors
  remained in the returned report and blocked export.

For equal coverage, alignment now uses the existing stable source-context order
to choose among candidates that individually match every referenced fact. The
same identity, period, value, entity, category, unit, scale, currency, audit and
reporting-basis checks remain mandatory. Competing larger supersets remain
ambiguous because their additional facts may differ. This changes presentation
references only; raw observations and their provenance are retained.

Claim validation now runs after the cross-slide repairs, and its findings form
the final export gate. Existing errors are not simply discarded: unresolved
contradictions and contradictions introduced by a later change still block
export. Repair history remains in the report's informational entries. No
document type, company name or financial metric is special-cased.

The extraction contract remains v23; analysis advances to v87. Restart the
application to load `2026-10-22-final-claim-revalidation-v163`.

Validation records:

- Focused source-alignment and claim-repair tests: 99 passed, including 12 new
  regression cases covering one-pass stability, source conflicts, competing
  supersets, late repairs and newly introduced contradictions.
- Full regression suite: 5,117 passed, 14 skipped, four existing
  dependency/event-loop warnings; no failures.
- Before the fix, a synthetic three-source summary reproduced the exact
  behavior: the first audit blocked, its final references were valid, and a
  second read-only audit passed.
- The saved `.882` already contains the later repairs, so replaying that file
  alone is not evidence that first-pass reporting was fixed. The synthetic
  first-pass and late-repair regressions cover that distinction.
- The original `.882` passed the normal financial export gate and real local
  rendering: 19 slides, no rendered QA issues or automatic layout repairs.
  Every slide was visually inspected. The document, profile, observations,
  analysis results, insights, selected topics and model-usage records remained
  identical; replay made no new model calls.
- Read-only financial audits of both `.781` and `.882` returned zero critical
  errors and preserved the entire loaded result. Their existing warning counts
  remained three and six respectively.

Existing limitations remain visible: source coverage and table alignment
warnings, a noisy source-derived chart caption on slide 10, wrapped table
periods on slide 11, and the data-index appendix following the Thank You slide.
These are not presented as repaired by this change. Local rendering does not
establish Microsoft PowerPoint rendering parity.

Local replay artifacts and audit are stored under `output/v163-882/`; focused
and full-suite logs are `output/pytest-v163-focused.log` and
`output/pytest-v163-full.log`. These generated files remain ignored by Git.
