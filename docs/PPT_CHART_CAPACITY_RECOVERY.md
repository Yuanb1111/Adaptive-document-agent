# Chart capacity pagination (v79)

A valid analysis can fail during PowerPoint generation when a multi-chart page
combines a two-line slide heading, a subtitle, chart headings, calculated change
annotations and an exact-data table. The earlier three-panel heuristic checks
chart titles and series density, but does not measure all these slots together.
The remaining native chart area can be below the readable minimum of 1.25 inches.

The compositor now catches only its own chart-capacity errors and paginates the
physical output with fewer panels. It removes pages created by the failed attempt
before retrying, preserves hero ordering, keeps supporting tables on the first
page, and leaves the semantic plan, raw observations and evidence unchanged.
Each recursive retry reduces the panel count. An unfit single chart still fails;
invalid evidence and unrelated generation failures are never retried as layout
problems. Native preflight and the rendered export gate continue to run.

Synthetic regressions cover financial and operating metric labels, themed and
unthemed pages, exact table values, source notes, partial-page rollback, hero
ordering and failures that must still block export. A locally supplied analysis
JSON reproduced the original capacity error. Replaying the same JSON after the
fix passed financial QA, native preflight and offline Artifact rendering, producing
a 31-slide deck. Private source-derived files are kept outside tracked files.

This change bumps `PIPELINE_VERSION` to v79 to invalidate presentation caches;
the extraction and analytical evidence contracts are unchanged. Rebuilding
PowerPoint from the existing analysis does not require new model requests.
