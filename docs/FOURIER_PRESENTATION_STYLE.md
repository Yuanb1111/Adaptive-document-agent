# Fourier presentation contract

Generated PowerPoint content follows the colour definitions on pages 18–24 of
`傅利叶基础规范Fourier VI Guidelines_V1.0_20240628.pdf` and the bundled
`FOURIER Light Version Template EN_251217.pptx`. The template's SHA-256 is
`07e054781157620ef205349ce7f1c079ffdedd57b3b075af8eb3fc18e3b58370`.

## Colour sources

`services/fourier_brand.py` is the single source for generated colours. The main
purple is `#7A24FD`; main text is black. Secondary text is `#666666` (60% black).
Surfaces and rules use `#F6F7F7` and `#DBDCDC`. Generated auxiliary colours use
the VI's exact values, including `#AB76FF`, `#F5B923`, and `#20EDF2`, rather
than the slightly different auxiliary values in the template theme. The
template's additional blue `#0086D1` is also supported.

Native charts share this palette. A deterministic map uses the actual series
or slice labels across the whole deck: co-occurring series have distinct colours
and repeated labels retain their colour. Unrelated single-series charts can use
the main purple. This assignment is categorical, not an inferred signal of good
or bad performance. Negative bars retain their fill and signed values. Stacked
and doughnut labels choose contrasting black or white; percentage labels retain
their percentage semantics. Excessive colour requirements fail explicitly
instead of silently repeating colours within a chart.

Original template layouts, masters, image bytes, logo sizes and positions are
preserved. Their embedded artwork and gradient colours are not rewritten.
Source-document pictures are evidence and are not recoloured.

## Text and layout

Content headers use Arial Bold 32 pt and purple Arial Regular 18 pt subtitles.
The original header width leaves room for the unmodified template logo. Long
analytical titles may use the planner's existing section heading as the title
and retain the complete claim in the subtitle. The analytical question remains
in notes. The generator does not invent a new heading or shorten a claim.

Standard covers use 36 pt titles and 26 pt subtitles. Overview and commentary
body text is 16 pt, with 18 pt local headings and 16 pt chart headings. Dense
data tables, chart labels and provenance footers retain their smaller functional
type sizes. Wrapping, pagination and continuation pages preserve evidence and
complete supporting copy rather than shrinking text to fit. User-selected image
cover layouts remain a separate explicitly selected illustration layout.

## Export checks

`validate_generated_brand` runs after content preflight. It rejects unsupported
explicit RGB colours in generated slides/charts and native chart series that
depend on automatic Office fills or outlines. This check does not inspect image
pixels or recolour original artwork. Regression tests separately verify label
contrast, repeated-series consistency, native chart values and preservation of
template pictures and their geometry.

The existing local render gate still renders every slide and checks geometry,
page count and evidence preservation. A brand colour check is not a guarantee of
identical rendering in all versions of PowerPoint. Changes to these export rules
invalidate the PPT build cache through `PIPELINE_VERSION`; they do not invalidate
extraction or LLM analysis caches and do not add model calls.
