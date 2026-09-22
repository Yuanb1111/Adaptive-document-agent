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
