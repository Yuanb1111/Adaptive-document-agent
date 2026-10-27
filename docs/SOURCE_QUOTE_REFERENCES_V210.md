# v210: exact source quote references and an early reporting prerequisite

The `.269` v209 checkpoint reached final source integration with an earlier
supplementary source read still marked failed. Both allowed reads had returned
the same quotation joining separate source passages with an inserted ellipsis.
The literal-source validator correctly rejected it. Report generation continued
despite that known prerequisite failure, and the final error obscured the source
read's actual cause behind an incomplete-integration message.

Supplementary source reading now exposes the complete requested pages as
page-local, numbered source blocks. Blocks are at most the existing 1,000
character quote limit; concatenating each page's blocks reproduces every original
character, including whitespace and qualifications. The model selects evidence
IDs and writes its source-supported finding. Python expands only those IDs into
the exact source page and text. It does not choose relevance, rewrite evidence,
infer page numbers or treat a reference as semantic approval. The complete pages
remain available to the model, and downstream source integration and independent
review remain mandatory.

Unknown references use the existing second semantic read and then fail closed.
Legacy literal responses remain supported and must pass the same literal-source
check. Blank spans cannot support a found finding. Both the original reference
response and expanded literal response remain in attempt diagnostics. The
existing two-read/one-format-repair limits, 18,000 source-character input cap,
three-page target limit and eight-quote limit are unchanged. All model requests
still use LLMGateway and its privacy controls.

Before dependent report generation, the orchestrator now checks saved source
read status. If a read remains unfinished after its bounded recovery, it returns
a `source_reading` partial checkpoint with the original reason, physical pages,
read history, extracted observations and completed calculations. Invocation-owned
background work is drained. A user-triggered reporting retry uses the existing
bounded reread mechanism; the checkpoint does not silently add retries, certify
absence or relax final export requirements.

The first real run through the ordinary reporting retry API completed that source
read, then exposed a separate deterministic presentation defect. Adding a
separate-period coverage note to an unscoped model-authored bullet created an
empty evidence list for the original bullet. The native plan validator rejected
the inconsistent metadata before export.

Recovered insight copy now carries its exact existing task-input IDs for each
bullet. Period-scope preparation preserves explicit per-bullet bindings. For
previously unscoped copy it makes the already-linked chart, block and insight
inputs explicit before adding separately bound coverage references. It does not
infer support from matching labels or pages, add periods to charts, change raw
values or authorize a claim. Malformed existing bindings remain unresolved;
the 40-reference capacity and normal semantic/numeric validators still apply.

The pipeline version advances to v210. Extraction-v23 and analysis-v88 contracts
remain unchanged. Private checkpoints, original source data, API diagnostics and
generated reports remain outside Git under ignored local paths.

## Validation

- 29 existing source-coverage, source-recovery, retry and finalization tests passed.
- 11 new tests passed: lossless full-page round trips, exact reference expansion,
  ellipsis correction within the existing second read, unknown/unowned IDs,
  blank spans, format repair, legacy literal rejection, and normal orchestrator
  retries stopping before editorial requests while preserving source and math.
- 1,352 source, pipeline, reporting-checkpoint, privacy and Local Only regression
  tests passed; five tests requiring external fixtures were skipped. Counts
  overlap with the focused runs above.
- 28 period-scope/editorial/source-context tests and 24 focused period-binding
  and insight-recovery tests passed. These include appending versus merging a
  coverage note, unchanged raw charts/data, exact existing per-bullet scopes,
  idempotence, and refusal to guess malformed bindings.
- 1,176 broader presentation/period/scoped tests passed. One Streamlit test
  timed out while Python's socketpair waited on loopback accept in the sandbox;
  the unchanged test passed separately with loopback access enabled. No test
  assertions or application networking rules were relaxed.
- Local replay of the exact retained pre-transformation slide inputs passed
  the complete presentation-plan validator with three annual input IDs on the
  original bullet and two interim IDs on its separate coverage note. Original
  document, observations, calculations, insights and charts were unchanged.
- The first real normal-API retry used 36 calls in 432.4 seconds and failed the
  native bullet-evidence gate described above. It is not a successful export.
- The second normal-API retry completed reporting and strict PPTX export in
  699.9 seconds with 56 real gateway calls. No historical model responses were
  injected and gateway caching was disabled. The diagnostic harness migrated
  only the in-memory checkpoint version from v209 to v210 after confirming
  unchanged extraction/analysis contracts; production version checks were not
  relaxed. This was a saved-extraction reporting retry, not fresh PDF extraction.
- The result passed the production completion gate and all physical budgets.
  Reloading the exported PPTX confirmed 17 total slides, 16 body slides and one
  data-index slide. Local strict rendering QA passed on its first attempt with
  no issues or layout repairs. The original document, observations and calculated
  results matched `.269`, and the original input file remained unchanged.
  Artifact SHA-256:
  `71a245423ba1ac4e692b0fa7b0ba60c73c5d3e967ad6b422c7f62188238515f5`.
