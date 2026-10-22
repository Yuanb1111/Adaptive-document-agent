# Retained topic scope (v160)

The saved v159 run ending `.031` completed analysis but failed PowerPoint export
with two `chart_topic_mismatch` errors. Its selected annual and interim topics
included revenue, product mix and gross profit as a share of revenue. Recovery
narrowed their headings to revenue while retaining the selected margin charts.

The share parser treated `as` inside `as a share of` as a conjunction when an
earlier clause also mentioned share. The resulting unbound claim triggered a
comma-based heading fallback that discarded other selected measures. Slide scope
validation then rejected the margin charts against those narrowed headings.

The parser now preserves ratio phrases while still separating independent claims
joined by `as`. When a share comparison cannot be bound, recovery retains the
complete model-authored neutral question instead of dropping its measures.
Directional claims and explicit denominators still require their own evidence.

Parallel-panel scope validation recognizes a measure named in the retained model
topic title or question only when its exact observation belongs to the selected
series, current theme and current slide (including linked charts). The observation
must be valid, finite, period-bearing, sourced and free of anomaly notes. This
establishes scope only: it does not prove a ratio, arithmetic relation, direction
or causality. Chart captions and numerical claims retain independent validation.
Like-for-like panels do not use this scope exception.

The extraction contract remains v23; the analysis contract advances to v84.
Restart the app to load v160. Export replay uses the saved completed analysis;
it does not require re-extraction or a new provider request.

Validation replays the original completed `.031` checkpoint through the real
`export_pptx_with_report` API with the local artifact renderer, without force or
manual changes to its data. It exports 17 pages: 15 body pages and 2 Data Index
pages. Financial QA has no critical errors; native preflight and rendered QA
pass, with no rendered issues or repairs. All pages were reviewed in a contact
sheet, with full-size inspection of the listing-basis, annual/interim mixed-metric
and zero-crossing cash-flow pages. Existing source-alignment warnings remain;
the generic zero-crossing warning does not manifest as a label collision in the
rendered cash-flow chart. This replay does not certify a fresh provider analysis.

Assertions confirm that observations, analysis results, model topic selection and
LLM usage remain unchanged. Regression tests cover ratio phrase boundaries,
explicit denominators, neutral-question recovery, exact topic/theme/slide ownership,
invalid or unsourced observations, like-for-like exclusion and independent chart
caption rejection.

Validation results: 185 focused tests passed; the complete suite passed with
5,071 passed, 14 skipped and four existing dependency/event-loop warnings.
