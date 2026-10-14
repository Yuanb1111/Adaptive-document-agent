# Literal cardinal evidence and the .854 failure

The saved `analysis_data - 2026-10-14T101811.854.json` ran v126 and correctly
retained a partial result with `retry_from=reporting`. Its opening theme failed
source preflight with `unsupported numeric claims ['5']`. The targeted repair
returned the same paragraph and fact IDs, so unchanged-draft protection stopped
the introduction and PowerPoint export.

PDF page 11 literally states that 22 models were six-axis models and **five**
were four-axis models. The generated Chinese paragraph said `5款`. The numeric
validator recognized digits but not that English cardinal. This is a notation
equivalence, not a calculation inferred from 27 minus 22.

## Change

- A shared, bounded cardinal parser normalizes exact English coefficients below
  1000 in temporary validation text. It handles simple counts, tens, hundreds,
  hyphens and explicit signs; complex scale expressions and malformed hundreds
  remain unrecognized. Raw page text, fact values and literal quotes stay intact.
- Numeric and typed quantity checks use the same notation contract in both
  source and claim. Currency, magnitude, percentage and denominator checks still
  reject invented units, changed signs and changed amounts.
- Cardinal expansion is limited to claim checks against literal quotations.
  Planner phrases describing evidence structure (such as "three series" or
  "one source table") keep their existing validation against observation cells;
  they do not become purported measurements from those cells.
- A complete quoted table row can bind a month duration to its exact literal
  header date. Only that complete supported date label is exempt from count
  checks; its duration cannot authorize a customer count or another duration.
- Mandatory independent semantic review and bounded repair limits remain in
  force. Numeric equivalence does not certify an association or opening meaning.

## Validation

The original .854 source failure was reproduced before the change. Offline
replay after the change checks all **24 retained paragraphs across three
authored themes** without source-reading or draft-source failures. Six themes
were not authored in the saved run. The opening has no accepted semantic review
in that record; it still requires a new independent review on retry. No completed
new presentation or live model run is claimed by this replay.

`tests/test_number_word_evidence.py` covers notation equivalence, the translated
count, exact source preservation, unrelated-page counts, currency/magnitude and
percentage rejection, denominator retention, table duration binding, and entry
into mandatory semantic review without an unnecessary content repair.

Validation on the final change:

- Full offline suite: **3,655 passed, 8 skipped**, with four existing LiteLLM
  event-loop cleanup/deprecation warnings from mocked transport tests.
- Focused introduction, Brief, pipeline, planning and rendering checks:
  **173 passed**.
- Final saved-record replay: .854's 24 paragraphs and .065's 66 paragraphs
  have no source-reading or retained-draft source failures. Unauthored themes
  and fresh semantic review remain pending in both saved records.
- `git diff --check`: passed. No live provider requests were made.

Pipeline contract: `2026-10-14-cardinal-evidence-v127`.
Analysis contract: `analysis-v69`; extraction remains `extraction-v18`.
