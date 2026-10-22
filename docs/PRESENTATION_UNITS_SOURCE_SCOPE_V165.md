# v165: chart units and source scope

## Problems

Source-row composition candidates copied `table_context` into their titles.
That metadata can be a mixed-column unit line, so a percentage chart inherited
an unrelated ASP currency/unit caption. The raw observations and percentage
values were correct; their displayed heading was misleading.

The closing-page warning treated absence of a literal summary quotation as
proof that additional evidence had not been incorporated. Literal referencing
does not establish semantic coverage. Sparse-page packing then moved the
warning into a company introduction page unrelated to the cited source pages.

## Changes

- New source-row composition titles use the explicitly plotted column. Existing
  saved titles are repaired only when they exactly match the old mechanical
  `table_context — column` construction, optionally followed by a retained
  period. Authored qualifications are preserved. Explicit denominator evidence
  continues to scope the percentage caption; no currency, denominator or unit
  is guessed, and raw metadata remains unchanged.
- Missing literal quotations are described as a supplementary-source citation
  limit, without asserting a material omission. Duplicate citation signals are
  combined while retaining every affected physical page.
- Genuine incomplete source checks and unresolved topic assessment remain
  visible as limitations. This change does not complete those reviews, mark
  them successful, or certify comprehensive document coverage.
- Limitations appear on a dedicated `Scope and limitations` page. A persistent
  slide role protects it from sparse-page packing in both directions, including
  after saving and reopening. The contents entry follows the same title.
- Speaker notes retain source checks, quotes, attempts, topic-coverage records
  and the superseded closing plan. Internal review questions and transport
  details do not become audience conclusions.

## Validation

Focused regression tests cover saved-analysis repair, currency/physical/table
metadata, unchanged native chart values and evidence, snapshot periods,
authored qualifiers, source-warning accuracy, scope-page persistence and cases
where no limitation should be manufactured. The initial focused run passed
58 tests.

The final full regression run passed 5,146 tests, with 14 skipped and four
existing dependency/runtime warnings (`output/pytest-v165-full.log`).

The `.848` replay uses the previously reviewed v164 language mapping, with new
display copy translated and independently checked through the configured
LLMGateway under the user's existing DeepSeek authorization. The original
analysis JSON is not overwritten. Outputs, model audit and rendered pages are
kept in ignored `output/v165-848`.

The actual replay passed ordinary evidence, language, budget and local rendering
gates without force export: 19 slides, five introduction slides, 16 native charts
with types/categories/series/values identical to v164, no Chinese display prose,
and unchanged original facts and source-check records. The application-share
caption now names its evidenced revenue denominator and uses `Share (%)`.
The scope page is slide 16; no review text is packed into the introduction.

Changed pages were visually inspected. The other 12 rendered PNGs are byte-for-
byte identical to the already reviewed v164 pages. Validation records are in
`output/v165-848/audit.json` and `content_validation.json`. The only remaining
preflight warning concerns the existing Data Index after the Thank You slide;
local rendering passed with no issues. This does not certify PowerPoint renderer
parity or clear the retained substantive coverage-review limitation.
