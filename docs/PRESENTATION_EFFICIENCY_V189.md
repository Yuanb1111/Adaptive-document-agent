# Presentation efficiency v189

The reviewed v188 run completed analysis in 1,063,831 ms and export in 27,632 ms.
It recorded 111 model calls and 166,478 reasoning tokens. These are observations
from one private diagnostic export, not a benchmark or a promised speedup.
Introduction work overlaps the foreground; individual model latencies must not
be summed as elapsed pipeline time.

## Changes

- Introduction audience review, introduction layout and physical-budget selection
  use the existing configurable editorial reasoning reduction. Initial analytical
  topic selection, insight generation and assurance scope review retain their
  existing reasoning policies. The model still decides meaning and importance.
  No evidence gate, response capacity, retry budget or provider route is removed.
- Initial topic selection factors repeated exact series cells, qualifications and
  definitions into self-contained wire dictionaries. Selectable IDs stay literal.
  Every raw/normalized point, scope, source page and qualification is recoverable
  with its original JSON type and ordering. Canonical data and the existing
  bounded coverage/repair contexts remain unchanged. Encoding is used only when
  it is smaller than the original request.
- Short text-only continuations from one planned chart group can use spare space
  on sibling chart pages. Copy stays at 16 pt. Native charts retain minimum plot
  dimensions, values and order; fixed labels and qualifications cannot be covered.
  Only exactly repeated visible paragraphs are de-duplicated. Matching source
  footers and geometry validation are required. Complete original copy and notes
  are retained in the destination notes. Unfit candidates leave the original
  pages intact. Both budget measurement and final rendering use this compositor.

## Local replay findings

On the supplied private export, the initial topic payload decreases from 323,229
to 231,567 characters (28.4%). The affected three-page chart group becomes two
pages with the same three native charts and the complete visible copy. This
reduces measured page cost before any model decides to omit analytical content.
It does not restore topics that were already omitted in the saved v188 result.

The full geometry replay decreases from 19 to 18 slides. All 12 native charts
retain identical ordered series values. Slides 9 and 10 were rendered in local
PowerPoint and visually checked for clipping and overlap. This geometry preview
is not a newly approved final export: the old localization review correctly
rejects the changed visible text combination.

Offline replay establishes transport size and layout, not model quality or new
end-to-end latency. A fresh provider run is still needed to measure those. Saved
localization approvals bind the previous visible strings and cannot approve a
new composition automatically. The v189 pipeline version invalidates finished
report/checkpoint reuse so changed display strings go through the usual language
inventory and review. Extraction and analytical cache versions remain unchanged.

Private PDF/JSON/PPTX files and rendered previews are not repository fixtures.
Synthetic regression tests cover lossless decoding, provider opt-out and endpoint
guards, retained chart data, source mismatches, minimum plot capacity and rollback
after failed geometry validation.

## Validation

- Related regression selection: 2,790 passed, 11 skipped, one Streamlit UI test
  deselected because of the previously diagnosed Windows event-loop environment
  limitation. This was 209 test files, not the complete repository suite.
- Final focused efficiency tests: 11 passed, including missing/mismatched source
  citations, preserved data, insufficient plot space and failed geometry rollback.
- Changed Python modules compile; `git diff --check` passes.
- No live model request was made for this change. Fresh end-to-end latency and
  semantic-output quality still require a normal provider run.
