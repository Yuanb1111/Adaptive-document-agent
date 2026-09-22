# Presentation accuracy review, 2026-09-22

This change addresses generator defects found during an exported-deck review. It does not introduce issuer-specific rules or change the LLM gateway, source evidence, or Local Only policy.

- Composition candidates separate explicitly labelled totals from components. Totals remain linked through `total_observation_ids`; retained totals must reconcile, including for amount stacks. The common UI/export validator rejects qualified aggregate labels plotted as components. Similar spelling or a coincidentally matching sum is not evidence of a total.
- Borderless extraction uses positioned year headings and centered superheaders to resolve annual/interim and snapshot groups, including single-row tables. It retains raw header tiers. Mixed durations without a supported boundary remain unresolved with a warning. Explicit flow metadata takes precedence over metric-name display heuristics.
- Cash movement narratives preserve signed source endpoints. Pairing for correlation rejects incompatible annual/interim samples instead of silently selecting a favorable subset.
- Legacy exports use the shared lossless compositor and truthful series headings. Complete findings and overview copy continue onto additional pages, preferring sentence boundaries. Planned narrative summaries use the same text pagination. Extraction statistics move to the appendix, contents columns balance, and source-page ranges compress without losing citations.
- Appendix columns split by reported period basis, with up to six periods per page. Composition charts resolve palette collisions locally and omit labels that cannot fit thin segments; native workbooks and the appendix retain exact values.
- Table cache and Streamlit result identity advance to v11. Previously downloaded PPTX files do not change; users must rerun analysis after deploying the code.

Regression tests use synthetic documents and observations. A separate local, read-only check against PDF pages 328, 331 and 333 confirmed snapshot dates and the two 6M2024 turnover observations. Source PDFs and diagnostic renders are not repository fixtures.

The changes do not certify that every model-generated deck matches a reference presentation. Content selection still depends on the evidence catalog and validated model plan. The latest full cloud model run was not replayed as part of the offline tests, and some older specialized layout helpers still use bounded text fields.

## Follow-up: normalized units, source context and runtime cache identity

- Currency movement formatters no longer guess billions from small numbers. Numeric inputs use an explicit scale multiplier; observation inputs are already normalized and ignore chart display scales. Missing observation currency is not replaced with RMB.
- Comparable-series identity retains source section and table context. Same-label measures in different contexts cannot form one trend. Correlation samples may vary in their sample dimensions, but dimensions must match within each pair and period/unit/context checks still apply across samples.
- An explicitly named group total closes the source hierarchy. Subsequent numeric rows remain independent until another source heading. Subtotals do not close the parent. No issuer names, values or page numbers drive this rule.
- Appendix rows retain category, currency and source identity; conflicting values for the same identity and displayed period cannot overwrite one another. Composition checks now also run on fallback exports without a presentation plan.
- Extraction, session result, native PPT build and rendered QA caches incorporate `2026-09-22-unit-context-v12`. The UI displays the loaded pipeline contract and QA JSON retains it. Code on disk still needs a process restart when source watching is disabled; the marker is not a claim of a Git commit or deployment verification.
- Restored `Download analysis data (.json)` beside CSV, with an explicit document-content notice and independent export failure handling.

Read-only local extraction against source pages 313, 328, 331 and 333 verified separate cost/inventory series, independent net assets, component sums matching both reported totals, and a bill-receivable narrative starting at RMB 21k and ending at the June 2024 snapshot. No cloud model, deployment, source PDF rewrite or external upload was used. Automated tests cover synthetic equivalents; a complete new cloud-generated presentation remains to be verified after deployment.
## Opening-slide editorial revision (2026-09-22, v13)

- Replaces legacy overview/section-inventory continuation pages with one opening
  brief. Discovery supplies up to three short, source-grounded `overview_points`;
  cached profiles use clearly labelled, complete-sentence excerpts.
- Replaces repeated findings continuations with one readable summary. Semantic
  priority still comes from model insights. Linked, compatible observations can
  provide deterministic movement copy when the original is a calculation dump.
  Unlinked or incompatible inputs are never guessed from a title.
- Full overview, section inventory and findings remain in speaker notes and in
  the existing JSON/report. Complete selected caveats stay attached to claims.
  The chart analysis pages and financial validation gates are unchanged.
- Insight requests now include actual normalized input observations with their
  raw units, scales, currencies and periods. The prompt distinguishes normalized
  values from source-scaled values and prohibits diagnostic prose.
- Opening brief capacity uses actual text length (including CJK), fixed readable
  font sizes and dynamic row heights. No mid-sentence clipping or continued pages.
- Pipeline version is `2026-09-22-editorial-brief-v13`, invalidating prior session
  and export caches after deployment/restart.
- Verification: full regression suite and local rendering of opening-page replay.
  Replay is a layout test, not a fresh cloud model analysis or proof of future
  model editorial quality. The next deployed run still needs content review.

## PPT4 source attribution and layout revision (2026-09-22, v14)

- Company recovery prefers a complete, unambiguous cover legal name. Relevant
  industry/ownership pages are not automatically issuer evidence: only bounded
  issuer-labelled windows may supply fields. Cited headquarters and other scalar
  fields are rechecked against those windows. Suffix fragments, listing headings
  and product fragments from adjacent table columns are rejected.
- Planned company overviews now use the same flat opening brief as the legacy
  path, with readable text, complete field values and full source copy in notes.
- Planned summaries recover each technically worded finding from its exact
  linked, compatible inputs. Four priority findings can use two flat columns;
  complete claims and caveats remain intact. A source-derived metric heading can
  replace an overlong heading, while the original heading remains in notes.
- Borderless extraction retains a parent heading before the first numeric row
  and a wrapped first-child label. Explicit parent qualifiers propagate through
  observations, chart headings and appendix labels without changing raw values.
- Boilerplate fallback slide titles name their actual selected measures. Paired
  snapshot-chart dates wrap over two lines without losing day/year/audit markers.
  Single-metric pages use the shared title geometry.
- Pipeline identity is `2026-09-22-source-context-v14`. Previously generated
  files are unchanged. Restart and rerun after deploying this version.

Verification includes synthetic regression tests and four locally rendered
pages covering profile, four-finding summary, qualified child metric and paired
snapshot charts. Read-only extraction against the original PDF confirms the
cover identity and retained grant-parent/first-child text. The latest cloud-run
analysis JSON was unavailable, so the render is a bounded regression replay,
not a complete rerun or certification of future model-generated content.
