# Evidence context and analytical coverage (v85)

The Agent now supplies source context and reviews omissions without a document-type
checklist. Raw values, page evidence and existing numerical validators remain the
authority for published facts.

- Extraction preserves a literal first-group heading when its matching named total
  bounds the source rows. Short headings and bare total boundaries also retain scope.
- Insight generation retrieves bounded source, neighboring and lexical-match page
  excerpts locally. A reported explanation must quote the exact supplied passage and
  page; unsupported explanations fall back to the validated calculation with an audit.
  Absence from these excerpts never proves absence from the entire document.
- Topic selection receives complete reported points, including separate exact source-row
  period views. One bounded LLMGateway review decides whether uncovered evidence is
  material or redundant and records each inclusion/exclusion reason. It does not force
  particular metrics. Failed or oversized reviews retain valid topics and mark coverage
  as requiring review. Annual/interim and definition checks still apply.
- Executive briefs receive explicit character limits and a literal table row/header
  guide. Continued topic pages are merged as retrieval anchors. Failed model writing
  can use comparable evidence from selected tables as well as charts in both web and
  PowerPoint summaries. Closing capacity favors representatives of model-selected
  questions before repeated findings, with the existing claim checks unchanged.
- Completion notifications use a compact card, accessible switch and small test button.
  Audio playback and the sound preference are removed, including legacy saved preferences.
  Verified exports alone produce silent messages; cached reruns remain deduplicated.

Extraction v3, analysis v42 and pipeline v85 invalidate affected checkpoints. To apply
the new source and topic behavior to an existing PDF, use **Reanalyse PDF (ignore model
cache)**. Previously downloaded artifacts remain historical results.

Synthetic regressions cover financial, operational, survey, research and Chinese
evidence. Browser verification mocks the OS boundary and tests enabling, silent test
messages, completion, cached reruns and responsive layout. Live-model selection and
operating-system notification delivery still depend on the configured model/browser.

Final verification: 2,860 Python tests passed, 8 optional real-render/Linux checks
skipped, and all 7 frontend notification tests passed. Windows SDK tests initialize
TLS and the cached tokenizer before their environment-isolation probes; external
HTTP remains intercepted. Two harmless pytest plugin-rewrite warnings remain.
