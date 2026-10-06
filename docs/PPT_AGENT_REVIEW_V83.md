# Evidence context, presentation organization and completion notices (v83)

The changes apply to arbitrary documents and model-selected topics. No issuer names,
page numbers, industry workflows, or source values are embedded in the implementation.

## Evidence and editorial behavior

- Insight input includes the source row's retained parent and category scope. A generated
  narrative that drops that explicit scope is withheld, with its original draft and
  evidence preserved in the JSON audit. This prevents a child row from being promoted
  to a differently scoped measure merely because its label sounds familiar.
- Literal quotation matching normalizes typography and table dot leaders, without
  removing words, quantities or qualifiers. Introduction repair retains independently
  verified items after its bounded retry; a failed item no longer erases another valid
  introduction page. Page-title numbers are also checked.
- Executive-brief quantities may use the units of a uniquely bound, complete, resolved
  quoted table row. Units and date headers must occur in the supplied source context.
  Currency, magnitude, accounting sign, complete unit denominator and date scope remain
  mandatory. Header digits cannot authorize unrelated numeric claims.
- Summary fallback groups physical continuations by logical topic, retains category
  labels and price precision, and deduplicates by complete facts rather than rounded
  display strings. Distinct facts with identical rounded wording use exact values.
- Ratio definitions are bound to explicit source formulas and their observations.
  Definitions and relevant limitations appear with the associated visual.

## Presentation organization

- Exact duplicate fact tables within the same authored topic are omitted from the
  displayed plan; all original records and corroborating sources remain available.
- Chart continuations are balanced without dropping charts or shrinking them into
  unreadable grids. Matrix row/header dimensions use actual text measurements.
- Coverage pages retain substantive limitations; selection decisions remain in audit
  notes. Fitting appendix themes stay together instead of splitting a composition.
- Verified findings take priority over generic monitoring sentences in the closing.
  Complete compatible evidence remains beside its conclusion.

## Browser completion notifications

Streamlit 1.53+ is required for the frameless component. The user enables notifications
with **Enable completion notifications**, accepts the browser permission, and can enable
**Play a short sound**. **Test notification** verifies settings and re-arms sound after
a refresh. Permission is requested only from the user's button click.

Notifications fire after the PowerPoint passes export checks, the download button is
available, and progress reaches 100%. A failed export never emits a completion event.
The same analysis or export cycle does not notify again on rerun or cache restoration;
explicit reanalysis, retry and **Regenerate PowerPoint only** create a new cycle.
Document text and filenames are not included in notifications or sent to a push service.

The browser tab must stay open and connected. It can be in the background, subject to
browser and operating-system policies. Closing the tab or losing its connection can
prevent delivery; this is not a server-side push service. Browser preferences and
deduplication state stay in session storage and do not trigger Streamlit reruns.

## Validation and limits

Tests cover source scope, ambiguous table rows, wrong signs/currencies/magnitudes,
multiword and compound denominators, header/date leakage, partial introductions,
summary precision, layouts, notification lifecycles and actual Streamlit startup.
Frontend tests mock the OS notification boundary; they do not grant real site permission.

Final verification: 2,724 Python tests passed (8 skipped) and all 7 frontend notification
tests passed. The Windows test runner initialized TLS and cached the public tokenizer
vocabulary before credential-isolation tests scrubbed the process environment. Provider
requests in those tests were intercepted; no paid model calls were made.

The latest saved analysis was also replayed offline using the saved model selections,
with no new model requests. All 16 native charts retained their category, series and
value data, and raw observations remained unchanged. Native and rendered export QA
passed. The old file contains no recoverable introduction draft, and its saved editorial
brief still fails selected-topic coverage after invalid items are removed. Those missing
model outputs require a fresh analysis; the replay correctly retains the evidence-based
summary and the visible introduction limitation.
The replay produced 22 slides from the original 30, with a single Contents page.

The analysis cache version is incremented to v41 and the pipeline to v83 so older
analytical claims are not silently reused as newly validated output. Extraction stays
at v2 because the raw extraction contract has not changed.
