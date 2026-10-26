# Physical continuation layout v197

The v196 diagnostic ending `.437` failed introduction layout with a five-slide
body budget. Its recorded page history was 7 -> 7 -> 6. The final draft contained
four logical groups, each with one paragraph. Two paragraphs were 1,217 and 1,244
characters, and both fitted their native template body regions intact.

`split_compact_item` nevertheless started with a 1,200-character ceiling because
`SummarySlideItem.text` had that schema bound. It split those paragraphs into
1,198 + 19 and 1,198 + 46 characters. Repeated headings on the tiny continuation
items prevented them from sharing the full first page, adding two unnecessary
slides. The model's complete final copy needed four physical slides, not six.

The v192 final-repair condition did execute: its recorded choice evaluation was
infeasible. The same premature splitting inflated the measurements of full-copy
inline alternatives, so the controller used a second rewrite instead. This was
a lower-level pagination defect, not another missing final-repair invocation.

## Change

The rendered item storage bound now matches the existing 6,000-character authored
copy bound. Continuation layout first tests the whole bounded paragraph against
the native template at the existing font sizes, including heading, wrapped title
and footer reservations. It decreases chunk size only when that geometry fails.
The storage limit is not permission to overflow a slide.

Real overflow still produces exact ordered continuations with their source
bindings and provenance digest. No words, numbers, units, qualifications or
meaning references are removed or rewritten. The hard five-slide budget, model
choice/refusal rules, source checks and fresh independent meaning review remain
unchanged. No retry allowance or font-size reduction is introduced.

## Recorded replay

```text
python scripts/replay_summary_layout.py path/to/analysis_data.json --recorded-final
python scripts/replay_summary_layout.py path/to/analysis_data.json --repair-path
```

For `.437`, the recorded-final path uses the actual final draft with no model
call or simulated choice. It passes the real pagination controller, survives
page-model serialization, measures four pages and generates four slides through
the native PowerPoint renderer. Every body character is preserved; structural
fact binding, selected meaning coverage and layout checks report no errors.

The separate repair-path replay uses the recorded initial draft and first rewrite
with an explicitly mocked inline selection. It now runs `SummaryLayoutPages`
followed by `SummaryLayoutChoice`, with measured history 7 -> 7 -> 4 and four
native generated slides. That selection is simulated, not live semantic approval.

Neither replay certifies independent meaning or whole-analysis completion. The
native-generation check is not a visual screenshot review or a full report export.
Private source content and diagnostics are read in place and are not committed.

Regressions cover fitting paragraphs above the former character ceiling, native
rendering and exact copy preservation, model serialization, real overflow even
below 1,200 characters, continuation provenance, unchanged source data, no rewrite
for fitting copy, and rejection of oversized unsplit pages. Existing lossless
choice and independent-review tests remain required.

Validation: the focused continuation, physical-split, layout-choice and repair
trigger suites passed all 20 tests. A broader run across 142 introduction,
summary, compact-layout, presentation and cache-contract modules returned 1,728
passed, six skipped and one failed. The skips require an explicitly configured
private replay or Linux LibreOffice. The remaining UI subprocess test initially
could not import Streamlit; with the dependency path supplied it timed out after
90 seconds, including a retry with writable temporary directories. That UI test
remains unverified; the broad run is not an all-green result. Syntax and Git
whitespace checks passed.

The pipeline becomes v197. Extraction and analysis cache contracts are unchanged.
