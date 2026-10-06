# Presentation layout and context review (v82)

A review of a generated deck found a two-page agenda with only two entries on
the second page, an overview with narrow text columns and a small image below
them, and a summary continuation containing only one finding. The fixes apply
to the agent's reusable renderers and retained evidence structures. There are
no issuer names, document names, source page numbers, or document-type branches
in the new layout decisions.

## Layout

- Contents uses measured, balanced columns with 16-point text and flat numbered
  rows. It retains all authored section labels and ordering. Ordinary agendas
  fit one page; genuinely oversized labels and agendas still continue.
- An overview with a source image first tests a wide text column beside the
  uncropped image. It measures all headings and body copy before falling back
  to multiple text columns or existing pagination. Original sections and source
  citations remain intact.
- Three or four editorial findings try balanced column widths and readable
  body sizes from 16 down to 14 points before continuing. All original wording,
  qualifiers, model ordering, and evidence remain visible and in notes.

## Evidence and audience context

- A validated composition chart no longer uses a single component's label as
  its overall title. Only exact component labels or exact category inventories
  receive this correction; authored analytical claims are preserved. The same
  complete-composition heading is used for navigation. The native legend keeps
  all components, avoiding a repeated category-list subtitle.
- Key Figures explains an unaudited marker when it appears in the current or
  displayed prior period. A star in a metric's name does not trigger the note.
- Percentage level cards retain `%`; differences remain percentage points.
  Ratio definitions are displayed only when a unique source footnote is bound
  to the selected observation rows. Otherwise a percentage series may display
  one complete description sentence from its uniquely shared source table.
  Ambiguous or missing source context is omitted, never guessed from the metric
  name or an adjacent table's cached context label.
- Closing evidence retains every selected compatible observation, including
  intermediate peaks and reversals, with at most five period columns per table.
  Wider tables appear above their linked prose. Monetary values retain source
  precision in the existing displayed unit; original decimal digits correct
  only floating-point representation noise, never conflicting retained values.
- The existing appendix classifier no longer matches `current assets` inside
  `non-current assets` (or the corresponding liability labels).
- Coverage pages explain evidence limitations in audience language. Raw
  validation exceptions, internal identifiers, and rejected numeric tokens stay
  in the original analysis audit instead of appearing on the slide.

## Verification

Synthetic cases cover unrelated categories, manufacturing/survey-style measures,
unequal summaries, varied image proportions, missing or ambiguous definitions,
native chart preservation, monetary precision, and long evidence series.
The broad presentation regression run passed 772 tests with five optional
Linux LibreOffice integration cases skipped. A subsequent focused run passed
48 tests after the final precision and label adjustments (overlapping tests are
not added to the broad count).

An offline replay of the saved analysis passed evidence QA, native preflight,
and actual local Artifact rendering. The deck changed from 22 to 21 pages:
contents and summary each use one page, while complete closing evidence uses
two. All ten native charts retain exactly the original categories, series names,
and values. Source-derived inputs, intermediate renders, and generated outputs
remain outside tracked files. Cloud rendering still requires a hosted run.
All 21 rendered pages were reviewed. Native preflight retained two nonblocking
duplicate-value warnings where the starting percentage also equals the peak;
both values are valid. Rendered QA reported no issues.

The pipeline version is v82; extraction and analysis cache contracts are
unchanged. No model calls are required to regenerate this saved analysis.
