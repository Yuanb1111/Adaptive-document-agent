# Summary evidence and stage-specific repair (v120)

The private v119 diagnostic `analysis_data (102).json` records a blocked
introduction, not a successful PowerPoint export. Its first theme already
explained the company's actual business. Full Summary reading passed for physical
pages 10–21. Neither result proves final exported coverage.

## Numerical evidence

The early introduction has no analytical table model and reconstructs literal
source grids locally. Analytical labels omit attached footnotes: `Others` could
not match the complete source row `Others(1)`. Allow only attached numeric label
footnotes when matching the ordered row. Preserve raw source text, all cells,
page ownership, resolved column roles and ambiguity checks. Missing words,
reordered values, altered pages and monetary values presented as percentages
remain invalid.

A header such as `RMB in thousands/unit for ASP` defines a denominator and a
column scope. Strip `for ASP` only when it exactly matches the target column.
Otherwise the full header and the retained unit metadata disagreed on the basis,
blocking legitimate ASP quantities. Sales volume cannot inherit the ASP currency.

Offline replay of the saved first-theme draft now accepts the previously rejected
7.1%, 6.5% and 4.3% on physical page 12. It correctly identifies omitted per-unit
denominators in the saved ASP prose. A validation-only copy with those explicit
source denominators passes every deterministic first-theme presentation check.
This is not a semantic acceptance, a rewrite of the saved diagnostic, or an
end-to-end rerun.

## Capacity and retries

Authoring text now shares the existing 1200-character `SummarySlideItem` bound.
The preferred copy length remains short. Actual native layout capacity still
rejects oversized paragraphs or packs whole paragraphs onto additional theme
pages. A 601-character paragraph no longer fails merely at the old 600 boundary;
Python never truncates words, values or conditions.

Review reasons remain bounded at 2000 characters, with a preferred length below
160. Preserve the complete explanation rather than trimming it. Required opening
verdicts, exact part ownership, source evidence and independent semantic acceptance
remain mandatory.

Offline replay also accepts both saved second-theme responses previously rejected
by the 600-character schema, with their deterministic source checks passing. All
four saved third/fourth-theme review responses previously rejected by the reason
length schema now validate. The private diagnostic itself remains unchanged.

A reviewer schema failure gets one repair against the same source and the same
pages. Both attempts retain raw output and field diagnostics in the private audit.
Exhaustion blocks that review without rewriting already validated editorial copy.
Transport retries stay in the gateway; privacy failures and cancellation propagate.
Semantic rejection still permits one editorial correction. Returning the identical
rejected draft blocks immediately, retains the original failures and avoids another
review request. The repair prompt carries the previous draft and exact failures.

The pipeline version is v120 and the analysis cache contract is v65. Extraction
remains v12 because raw extracted evidence has not changed. All model requests
continue through `LLMGateway`.

## Validation boundary

New regressions cover percentage footnotes, column-scoped rates, invalid currency,
scale and denominator changes, 601-character copy, longer reviewer explanations,
same-copy reviewer repair, protocol exhaustion, repeated rejected drafts and a
successful evidence correction. Existing tests cover full theme coverage, native
export provenance and mandatory first-page business scope.

Windows local validation: the complete suite collected 3457 tests. It passed
3446, skipped eight opt-in rendering/font integration tests, and failed three
Gemini transport cases because the fresh Windows LiteLLM wheel lacked a populated
tokenizer cache. Those cases clear cache environment variables while forbidding
unmocked sockets. Preloading the public `cl100k_base` vocabulary in the same test
process made all three pass with the original network and credential guards still
active. This accounts for 3449 passing tests across the full run and focused
recheck; it is not reported as a separate all-green full run. `git diff --check`
also passed. Public vocabulary preparation sent no document content or model
requests. The temporary dependencies and cache are workspace-local and ignored.

No hosted standard/custom run or financial-appendix acceptance is claimed. The
diagnostic's separate extraction anomalies still require validation in a future
authorized end-to-end acceptance run.
