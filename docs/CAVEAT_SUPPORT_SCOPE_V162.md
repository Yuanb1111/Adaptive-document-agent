# Caveat support scope (v162)

The v161 run ending `.781` completed analysis and introductory semantic review,
then failed the financial gate during PowerPoint export. The only critical error
was `slide_topic_mismatch`: a reported-versus-adjusted loss page included listing
expenses, but the topic validator could not establish its supporting role.

The selected topic already owned this exact observation series. Its caveat named
listing expenses and disclosed that no earlier comparative was available. The
original page 310 explicitly defines adjusted net loss as loss for the period
adjusted for share-based payments expenses and listing expenses. The records
share the same source table, period, entity, dimensions, currency and scale.
The declaration check read the model's question, rationale and takeaway, but
omitted its caveats, so it stopped before checking this source definition.

The support declaration now also reads the retained model-selected topic's
caveats. This is not direct topic matching or semantic approval. The exact
observation must still belong to the selected series, current theme and current
slide; it must be valid, finite, sourced, period-bearing and free of anomalies.
The existing checks still require a same-scope source definition naming the
supporting measure and an anchor, or a source-bound signed subtotal. A caveat,
shared page or shared table alone is insufficient. Chart captions and numerical
claims retain their independent validation. Missing comparative values remain
missing; the fix does not insert zeroes or derive unavailable observations.

The extraction contract stays v23 and the analysis contract advances to v86.
Restart the application to load v162. A completed `.781` analysis can be replayed
through `export_pptx_with_report` without new extraction or provider requests.
The source data and original checkpoint are preserved.

Validation:

- Focused topic/source-scope regressions: 71 passed, including 17 new cases for
  caveat scope, missing proof, wrong ownership, incompatible scope and independent
  chart-caption validation.
- Full suite: 5,105 passed, 14 skipped, four dependency/event-loop warnings.
- Actual `.781` replay through the normal export gate: 19 slides, financial QA
  passed and local rendered QA passed with no visual issues or repairs. All 19
  pages were visually reviewed; the final replay's PNGs match those reviewed.
- Document, profile, observations, analysis results, insights, selected topics
  and recorded model usage remained identical; no new model requests were made.
- One existing non-blocking preflight warning remains: the data-index appendix
  follows the Thank You slide, so the final slide is not the Thank You slide.
  Local rendering does not establish Microsoft PowerPoint rendering parity.

Local replay artifacts are under `output/v162-781/` (ignored by Git): the PPTX,
`audit.json`, and full-slide render outputs. The full test log is
`output/pytest-v162-full.log`.
