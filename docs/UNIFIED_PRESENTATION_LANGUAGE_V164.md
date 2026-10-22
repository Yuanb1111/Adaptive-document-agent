# v164 — Unified presentation language

## Problem

The saved `.848` analysis identified its source as English, but the company
introduction was Chinese. The user's Chinese page-count instructions were not an
output-language request. Previously, localization ran only for an explicit language
requirement, and template/chart prose could remain English beside Chinese prose.

## Policy and implementation

- Resolve one presentation language: an explicit body/all language request wins;
  otherwise use the discovered source language. “Original” means the source
  language. Conflicting or ambiguous requests block export rather than silently
  selecting one. Legacy records without language metadata remain unresolved;
  their missing language is never guessed from the script of a user instruction.
- Share this policy with introduction, briefing and report planning prompts.
  Record the derived target and its origin separately from literal user requests.
- Prepare all display prose through `LLMGateway`, including titles, labels,
  chart display caches, template text and source-footer wrappers. Translation and
  independent semantic review are separate requests. Python preserves coefficients,
  signs, dates, periods, currencies and scales. Local Only keeps its existing
  gateway restrictions and never falls back to cloud.
- Preserve raw evidence, literal source-table cells/footnotes, identifiers and
  source workbooks. An official alternate-language company name may be used only
  when supported by bounded literal excerpts from its bound source pages; the
  model determines identity equivalence. Never manufacture a transliteration or
  replace a current name with a former name. Context fingerprints prevent reuse
  of translations reviewed without the current identity evidence.
- Lay out checked cover titles, introduction labels, whole claims and contents
  labels before calculating geometry. Native asymmetric columns and contiguous
  item grouping retain complete claims at the existing readable font size. Page
  and introduction budgets remain hard export gates.
- Check the actual composed/saved PPTX, including cached and force-export paths,
  against reviewed display copy. A prepared translation map is insufficient.
  Native introduction subdivisions are accepted only after exact reconstruction
  and evidence-locator verification. Native continuation/ordinal wrappers require
  checked base copy. Whitespace and established native unit spelling equivalents
  do not excuse changed numbers or untranslated prose.
- Explicit `m/s` speeds no longer enter the monetary-million quantity parser.
  Independent semantic review still checks their physical-unit meaning.
- Chart rows allocate width from series and legend-label space requirements.
  Capacity checks measure usable plot height after axes and legend reservations,
  so a dense composition chart cannot pass merely because its outer rectangle
  fits. Insufficient space triggers evidence-preserving pagination. Redundant
  KPI/table references to charts on another continuation do not create duplicate
  tables. This also addresses the user's follow-up about the undersized first
  chart in the three-chart row.

## Validation

The final full regression run passed 5,139 tests, with 14 skipped and four
dependency/runtime warnings (`output/pytest-v164-complete.log`).

Regression coverage includes source-language fallback, explicit override and
aliases, conflicting requests, changed targets, unlocalized actual slides,
unlocalized introduction bindings, native continuation labels, complete-item
reflow, page-bound name evidence, and monetary versus physical units.

The `.848` replay uses the configured DeepSeek gateway with the user's permission,
retains the input analysis and raw evidence, and runs ordinary evidence, budget,
preflight, language and local-rendering gates without force export. Output artifacts
and model audit details remain under ignored `output/v164-848`, not in Git.

The final replay contains 18 slides, including five introduction slides. All 18
slides were visually inspected; visible text and chart display caches contain no
Chinese prose. The 16 native charts retain the exact types, categories, series and
values of PPT84. The crowded three-chart page is now a large composition chart
followed by two readable supporting charts. No duplicate source table is added.

This fix does not certify the existing deck's other analytical or visual issues.
The review records the application-mix chart's noisy unit caption and the existing
source-coverage warning. The previously narrow duplicate table is now omitted
because all its values are plotted on the continuation. Remaining caption and
source-review issues are separate follow-ups. Rendering checks use the local
artifact renderer; they do not certify Microsoft PowerPoint rendering parity.
