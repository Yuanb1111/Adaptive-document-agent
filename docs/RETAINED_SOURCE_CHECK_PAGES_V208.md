# v208: retain original pages after a source-check failure

The `.660` v207 checkpoint failed during report assurance binding. Its earlier
supplementary source check had failed literal quotation validation. The audit
context builder included nominated source-check pages only when their status
was `checked_found` or `checked_not_found`. As a result, available original
pages containing the entity definition, opinion and covered periods were
missing from the audit writer/reviewer context. Later discovery selected
statement pages but did not recover those opening pages. Repeating the entity
correction instruction could not supply the missing evidence.

The audit context now retains every explicitly nominated source-check page
that exists in the document, with the same bounded adjacent-page expansion.
This applies to failed, incomplete and unchecked checks as well as completed
checks. The source-check status and raw page text remain unchanged. Prompts
explicitly distinguish a prior semantic check outcome from availability of
original evidence. Additional page discovery, exact binding validation and
independent review still run; retaining a page does not establish assurance or
repair a failed supplementary-source conclusion.

The existing complete-page request budget, bounded correction counts, Local
Only routing and final source-integration gates are unchanged. No evidence is
truncated or accepted automatically to fit a request. Expanded-context and
discovery fingerprints prevent stale approval reuse. Extraction and analysis
cache versions remain unchanged; the application version advances to v208.

Continuation and a fresh PDF run also exposed semantic review problems, retained
in local diagnostics rather than counted as successful runs. Prompt contracts
now explicitly distinguish hypothetical risk consequences from asserted numeric
changes, source-owned evidence inventories from final audience prose, and
faithful first-person/third-person attribution from invented attribution. Genuine
historical changes and unsupported assertions still require their existing
source-bound checks. Snapshot binding guidance now explicitly directs writers
to a covered dated snapshot counterpart instead of repeatedly reformatting a
flow-period header. No numeric/date predicate or independent-review gate changed.

## Validation

- 33 focused tests passed, covering all five source-check statuses, unchanged
  check/source state, exact entity correction with independent acceptance or
  rejection, source discovery, request limits and source identity feedback.
- 571 audit/source/privacy regression tests passed.
- 528 introduction and direction-review tests passed; one external fixture was
  skipped. Another 50 snapshot/header/binding tests passed after the clarified
  header guidance.
- Both exact original failed audit proposals completed with real model
  corrections and independent reviews after the missing original pages were
  supplied: four real calls, one existing binding correction per batch. The
  failed source-check status remained unchanged during this diagnostic replay.
- The saved `.660` extraction subsequently completed reporting and strict
  PowerPoint export through the production stage gates. Its final continuation
  took 319.8 seconds and 19 real calls, reusing source-bound approved audit
  batches from the preceding diagnostic checkpoint. The exported file has
  20 slides (19 body, one data index); actual exported budgets and local visual
  QA passed with no issues. A separate reload verified production completion,
  unchanged original document/observations and the exported slide budgets.
  This is checkpoint continuation, not a fresh PDF run.
- A separate fresh run through `DocumentOrchestrator.analyse_pdf` and strict
  export completed in 838.2 seconds with 110 real model calls. It used the
  unchanged original PDF, a previously absent cache directory and no retained
  checkpoint or response-cache reuse. Its exported file also has 20 slides
  (19 body, one data index), with no local visual-QA issues. A separate reload
  confirmed production completion and actual exported budgets. Earlier failed
  fresh/continuation attempts remain recorded; this successful run is not a
  guarantee that all future stochastic model runs will succeed.
- Live verification records and private input/output files remain under ignored
  local diagnostic paths, outside the commit.
