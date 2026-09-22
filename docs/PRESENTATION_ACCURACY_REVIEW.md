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
