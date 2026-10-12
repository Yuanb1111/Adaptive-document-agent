# v111: bounded scoring and compact introductions

## Problems addressed

The v110 default run exported a presentation, but introductory fragments occupied
80 pages and the final briefing reverted to a metric inventory. Candidate scoring
was the largest foreground stage. A custom run failed with InternalServerError,
then appeared stuck at the fixed 66% milestone. Presentation requirements were
also entering discovery and analysis-priority context unnecessarily.

## Implementation

- Interpret user requirements immediately after ingestion. Send only resolved
  analytical emphasis into discovery/prioritization; retain language, detail and
  complete-table requirements for their own stages and final scope checks.
- Keep complete candidate comparison context and exact evidence IDs. Evaluate
  independent 40-candidate scoring batches with at most two workers; merge audits
  in source order and report real completed-batch counts between 66% and 69%.
  Local/stateful clients remain serial and all calls use gateway admission.
- Retry one transient transport failure, including HTTP 500/502/503/504. Never
  retry authentication, input-validation or unsupported-operation errors. Failed
  requests show stage/operation and attempt count. Disable retry while a run is
  active. SDK timeouts still govern in-flight calls; a service outage can still
  fail, and the code does not claim to cancel work already running upstream.
- Use the configurable lighter reasoning policy for structural Summary reading
  and bounded candidate ranking on positively verified endpoints/models. Keep
  deep meaning review defaults. Output budgets and policy version invalidate old
  structured caches, while raw extraction caches remain compatible.
- Read and preserve every source line/part. For long introductions, make one
  global thematic draft instead of a separate quota per source batch. Each
  paragraph can reference several exact reading facts from different pages.
  Python fills raw quotes and citations; independent review must accept every
  substantive part, rather than treating an attached ID as substantive coverage.
  A failed draft receives one bounded correction, never an unlimited raw-text
  fallback. Small introductory paragraphs are no longer split at 180 characters.
- Aim for three to five introductory pages, hard maximum five. Verify readable
  capacity against the actual configured template geometry, then check physical
  native pages and every visible evidence binding after export. Keep original
  parts, passages and decisions in the analysis audit. Qualitative paragraphs do
  not rescan numerical table cells; exact ownership and independent meaning
  checks still apply, and every numerical claim retains the original validators.
- Supply front-page identity evidence to the compact writer. Independently check
  the issuer/subject role, exact source spelling and complete stock codes before
  updating identity; advisors are not issuer evidence.
- Generate requested-language introductory and briefing prose directly where
  possible. Translate remaining display strings in at most two independent
  batches, with independent review and numerical/unit checks unchanged. Repair
  only failed IDs and merge timing/audits on the calling thread. Budgeted
  introductory copy must fit its readable boxes instead of expanding page count.
- Provide exact signed source-native quantity options before initial briefing
  generation, including header references and magnitude annotations. Retain
  source, denominator, period, direction and selected-topic gates. Unverified
  brief claims remain rejected. Standardize the appendix's monetary tie rounding
  without changing raw or normalized values.

## Verification and limitations

The final pre-commit local suite passed 3,349 tests with 8 skipped in 272 seconds,
including the qualitative numerical-scan optimization and final identity checks.
Mocks cover bounded server
retries, no authentication retries, real parallel overlap, caller-only progress,
reasoning opt-outs/output caps, exact five-page/70-part export, missing or tampered
part bindings, independent rejection of nominal coverage and incorrect identity,
and preservation of numerical gates and raw source tables.

The additional gateway integration reproduces a Summary reading HTTP 500,
recovers on the second transport attempt and then completes all 70 synthetic
content parts through reading, compact authoring and independent review. It
asserts both attempt records and the complete five-page result without bypassing
the gateway or weakening evidence checks.

Private default PPT71/analysis91 and the retained custom analysis90 regression
were replayed locally with explicitly authored corrected summary/briefing copy
and mocked reviewer decisions. The default fixture retained 70 source parts in
five introductory pages; its three corrected briefing claims passed literal
source and deterministic comparison checks. The custom fixture retained 62
parts in five pages, 38 original table fragments and the original footnotes;
every display string had a checked translation binding. Every raw source grid
compared equal before/after. All rendered pages passed local visual QA and
representative introduction, briefing and appendix pages were inspected.

PPT72/analysis92 received a further private local regression. Its original
company introduction was missing after two Summary reader InternalServerError
failures; the original executive briefing was unavailable after amount/source
checks. The replay retains the successful reading partitions, supplies explicitly
authored evidence-capture fixtures for the four failed Summary pages and runs
the normal complete reading and compact introduction checks. All 57 content
parts bind to five native introductory pages. The normal ExecutiveBriefWriter
receives exact source-native quantities before its first draft; three authored
revenue, loss and operating-cash claims pass literal currency/scale/sign/period
validation and source-bound deterministic comparison review without a patch.
Reviewer decisions are mocked; this verifies source/transport/export behavior,
not new model-generated semantics. Raw source tables compare equal throughout.
The 20-page replay passed visual QA; representative introductory and briefing
pages were also inspected after native rendering.

These are offline export/validation fixtures, not fresh model-generated output
or proof of independent table-detection completeness. No private PDF/PPT/JSON
was sent to a model provider or committed. Fresh default and custom runs remain
necessary to measure actual generation latency and semantic reliability. Full
source-table appendices inherently take extraction, native layout and rendering
time; they are preserved rather than shortened to claim a speed improvement.
