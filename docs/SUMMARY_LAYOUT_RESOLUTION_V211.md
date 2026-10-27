# v211: a complete final introduction layout correction

The `.840` v210 checkpoint failed in company-introduction verification. All three
measured drafts occupied six physical slides against the five-slide limit. The
first rewrite reduced occupied height but not the physical page count. Before
the final correction, Python found an exact-copy paragraph merger that would
reduce one two-slide group to one slide. The model returned `keep`, and the
binary selector spent the last correction without changing the overflowing
draft. It had no way to author a different coherent arrangement in that call.

`SummaryLayoutChoice` now offers two mutually exclusive responses within that
same final correction: select the measured exact-copy options, or provide a
complete replacement of the logical pages. When supplying replacement pages,
all exact-option choices must be `keep`; mixed patches are rejected. The
request includes full measured layout feedback, current copy, every selected
meaning and its owned source passages, plus the measured alternatives. A model
can reorganize related claims or shorten faithful headings when the offered
merger is unsuitable. Explicit refusal remains valid when no faithful layout
is possible, and still fails the unchanged hard budget.

Replacement pages use the existing constrained page/item schemas. Identity
fields are outside the editable schema. The model supplies meaning addresses;
Python binds each to its exact current paragraph without deciding semantic
coverage. Existing source ownership, original fact-ID preservation, mandatory
meaning coverage, body placement, physical geometry and fresh independent
semantic review remain required. The audit records whether exact choices or
replacement pages were applied, including the actual replacement and reference
count. Neither mode establishes semantic approval.

There are still at most two layout corrections, no additional model call or
format retry for the selector, and no change to fonts, slide caps, source
selection, calculations, Local Only routing or additive-repair restrictions.
All model access goes through LLMGateway. The implementation contains no
source-specific names, document types or fixed content. Pipeline version is
v211; extraction-v23 and analysis-v88 are unchanged. Private source material,
diagnostics and generated reports stay outside Git.

The first normal API continuation passed the introduction but exposed another
failure in audit-scope review. Flattened text placed a comparative unaudited
marker near the following year. The writer and reviewer repeatedly assigned it
to the wrong period, although the retained PDF line coordinates and rendered
page showed its actual column. The audit context had discarded those existing
coordinates and sent only flattened text. A reviewer also treated `unaudited`
as an invalid binding status despite its presence in the existing schema.

Audit reading now includes valid narrow source line anchors as literal
text with left/right/top coordinates in PDF points. Python only presents this
existing geometry; it does not assign a column, period, status or semantic
match. Complete source text remains unchanged, full precision source boxes
remain in the document, and both the writer and independent reviewer receive
the layout view and explicit instructions to check period/table ownership.
The reviewer also receives the existing two-status contract explicitly.
Blank columns still establish no assurance without a complete literal source
chain. The spatial aid includes lines no wider than 75% of the page's text span,
a purely geometric criterion. Full-width prose is not repeated as coordinate
rows; its complete text and qualifications remain in the source page. Missing
coordinates never establish missing qualifiers. Discovery includes full-page
reading costs and fingerprints the geometry;
its navigation request retains complete text, while subsequent source review
receives coordinates. Coordinate evidence counts against the unchanged 150,000
character review cap, and changed coordinates invalidate prior acceptance.

Discovery can choose different full pages on a new run. Two targeted audit
attempts exposed the capacity cost of repeating full-width prose as coordinates.
The narrow-line view avoids that redundancy, and both reviewer requests now
use the same compact JSON serializer as admission accounting. Only separator
whitespace is removed; whitespace inside source strings is untouched. The
18-page failed selection fits at 119,249 characters per largest actual batch
with every full page retained and the same 150,000-character limit.

The second normal reporting retry passed planning but failed briefing comparison
validation. Its source reviewer bound two distinct directional predicates to
one comparison and also inferred a direction from a factual `versus` statement.
The independent audience reader correctly rejected both. The combined item
was ineligible for the existing source-binding correction because `uncertain`
was classified as a content defect. Such ambiguity can now use that same single
correction to split exact comparison bindings. Audience text and evidence stay
immutable. Corrected bindings must pass source, quantity, duration, arithmetic
and fresh source-blind predicate review; actual direction contradictions remain
content failures, and unchanged ambiguity still fails without another loop.

## Validation

- The focused suites passed 43 cases before the native replacement check was
  added; the final layout choice/resolution/trigger suites passed 22 cases.
  These runs overlap. Tests cover both exact choices and complete replacements,
  unchanged two-call bounds, refusal, source/meaning omissions, malformed
  ownership, identity edits, ambiguous mixed patches, continued overflow,
  cancellation, Local Only mock routing, native text/page preservation and
  mandatory independent review after geometry success.
- A real Gateway call on the exact `.840` draft immediately before its failed
  binary selection chose the measured merger. The ordinary paginator produced
  five physical slides and the original fact-ID/identity and authored-coverage
  checks passed. It used one call in 11.9 seconds with caching disabled. This
  targeted check alone does not certify semantic acceptance or final export.
- The broader summary, introduction, compact layout, source-check, privacy,
  Local Only, slide-budget and pipeline-completion regression selection passed
  1,247 cases; six optional cases were skipped. These overlap with focused runs.
- The first normal API continuation used 66 real calls in 516.6 seconds and
  failed audit-scope review after completing the introduction. It is not a
  successful export. The diagnostic runner changed only the in-memory checkpoint
  version after checking unchanged extraction/calculation contracts; production
  version matching stayed enabled. No historical model responses were injected.
- Rendering the relevant original PDF page confirmed the comparative-column
  placement. No page or raw observation was rewritten.
- Twenty-seven focused audit layout/discovery/scope tests passed, including
  raw-state preservation, duplicate text at distinct positions, malformed
  coordinates, both model operations receiving geometry, discovery and accepted
  review invalidation on coordinate changes, and exact capacity boundaries.
- The final broader audit, assurance, privacy and Local Only selection passed
  563 tests. These overlap the focused cases above.
- The second normal API reporting retry used 41 real calls in 483.1 seconds and
  failed briefing comparison validation. It is not a successful export.
- A separate real-model audit of the original failed eight-target scene passed
  all production audit gates in 33.7 seconds with 11 calls and caching disabled.
  All four amount bindings were independently established for their correct
  periods, while percentages retained their separate unknown dispositions.
  Document, observations and calculations remained equal to their original
  model data. No prior model responses were replayed or approvals injected.
- Sixty-four focused direction, compound-binding, audit-budget and audit-layout
  tests passed, including unchanged ambiguity failing after one correction,
  wrong directions/evidence remaining rejected, and immutable audience copy.
- The final combined briefing, audit, assurance, privacy and Local Only
  regression selection passed 1,249 tests with no skips. Counts overlap earlier
  focused/regression runs and are not additive.
- Final continuation from the second reporting checkpoint passed production
  audit, budget, briefing, source integration, topic/introduction verification,
  requirements, localization, completion and strict export gates. It used 22
  real calls in 188.5 seconds with caching disabled and no response replay.
  This continued the retained analysis and presentation plan through production
  reporting functions; it was not a fresh PDF extraction or a single successful
  unmodified public-API run. The earlier public-API attempts remain recorded as
  failures above.
- Reloading the exported PPTX confirmed 20 total slides, 19 body slides and one
  data-index slide, within all production budgets. Local strict rendering QA
  passed on its first attempt with no issues or layout repairs. Original source
  document and 1,623 observations match `.840`; the 17 calculated analyses match
  the retained reporting checkpoint. Artifact SHA-256:
  `de40398907bd355fd1b93768a78e4e10fe9e7518a43676dac9bf257983c07ced`.
