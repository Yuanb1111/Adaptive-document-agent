# Executable report requirements

The optional **Analysis and PPT requirements** field is interpreted through
`LLMGateway` into bounded requirements before analysis and report generation.
The unchanged programmatic entry point is `analyse_pdf(..., analysis_focus=...)`.
Blank input adds no requirement interpretation or customization model calls.

## Supported requests

- Analysis emphasis: prioritize an evidence-supported issue or topic.
- Content detail: request concise, balanced, or detailed treatment.
- Chapter tables: append every detected table fragment in a named source chapter.
- Narrative language: localize audience-facing slide copy into the requested language.
- Page budget: request a maximum physical slide count, including the cover,
  existing Data Index, additional source-table appendix, and closing slide.

For example:

> 重点分析现金流和负债，公司介绍写详细一些；把 Financial Information
> 整个章节的所有表格放到 PPT 最后；正文用中文，原始表格保留原文。

Chapter names are resolved from the uploaded document's outline and physical-page
heading evidence. There is no fixed prospectus/Financial Information workflow.
Unresolved chapters and unsupported actions are recorded explicitly rather than
assigned guessed page ranges or executed as code. Conflicts are shown in the
results. They do not authorize weakening factual, financial, privacy, or export
validation.

## How requirements change generation

Resolved emphasis/detail/page-budget requests are supplied as trusted user
instructions to selection and report/presentation writers, separately from
untrusted PDF content. Their content fulfillment receives a bounded semantic
review, and supporting planned slide IDs are mapped to actual exported pages.
The review is an assessment of treatment, not proof of every factual claim;
existing evidence and financial validation still apply.

Whole-chapter table requests expand the digital table extraction scope independently
of the normal deep-analysis scope. Original physical table fragments are archived
before cross-page reconstruction. The additional pages do not automatically add
every cell to normalization, candidate scoring, or insight analysis. The appendix
uses these archived grids, including measures that were not selected for charts.

Source tables remain native, editable PPT tables. Wide/long tables continue across
pages with repeated period/column context. Original header qualifications such as
units and audit notes are copied visibly when separately retained; full raw headers,
page text and cell-coordinate provenance are in notes and the analysis JSON.
Short tables can share a page without changing their individual source context.
Every retained source cell is checked against actual PPT cells, including signs,
missing strings and fragments of long cells. Missing/changed cells block export.

Language preparation operates on a private native deck to identify actual display
copy. Translation and an independent semantic review use the configured gateway.
Numeric token counts, signs, dates, percentage symbols and literal currency/scale
tokens are checked again before applying translations. Unsafe or overflowing copy
keeps its entire original text and produces partial completion. Original chapter
table cells and chart workbooks retain source values and language. Local Only mode
uses only configured loopback model access and never falls back to cloud.

## Completion and limits

The results show each interpreted requirement, its status, reasons and actual PPT
pages where available. The same report is retained as `customization_report` in the
analysis JSON. Final export verification checks table cells, physical page count,
language coverage and supporting slide mappings. A page limit remains a requested
planning constraint; when source coverage/readability requires more pages, the
application retains evidence and reports the actual unmet limit.

**Detected table coverage is not certified coverage of every table in the PDF.**
Digital extraction can miss layouts and this release does not run OCR. Failed
extraction, OCR-required pages and uncertain fragments produce partial completion.
Even a successful cell comparison proves fidelity to retained extracted grids,
not that source detection was exhaustive. This distinction appears in the user's
completion report rather than being hidden behind an “all tables completed” claim.

The parser normally adds one lightweight model call, with at most one correction
for invalid interpretations. Semantic review adds a call for emphasis/detail;
language requests add bounded translation/review batches. Full-table requests
increase native slide creation and render verification according to chapter size.
There is no promised fixed generation duration. Existing scoring and analytical
reasoning depth is preserved.

Cache versions were advanced for raw fragment archives and executable requirements.
Old exported analysis/PPT files are not retroactively upgraded; upload again to
exercise this feature.

## Validation

`tests/test_report_customization.py` covers source-bound interpretation, unsupported
and ambiguous requests, blank-input behavior, extraction-scope expansion, preserved
raw/unselected cells, wide/long table pagination, short-table packing, visible header
context, tamper/missing-cell rejection, incomplete extraction reporting, slide-budget
conflicts, translation guards/review and finalization immutability. Pipeline, export,
privacy, reasoning-policy and UI regressions run alongside these tests.
