# v126: analysis evidence, completion and retry boundaries

This change starts from the local v125 revision used by the latest downloaded
analysis. It addresses nine reported reliability defects and the introduction
failure retained in that analysis.

## Saved analysis failure

The introduction failed after a corrected financial-position theme retained
Chinese calendar labels such as December 31 and June 30. The numeric gate treated
their numeric month spellings as unsupported quantities, while their English
source quotations spelled the months out. Calendar labels now retain a distinct
month/day identity across languages. Years stay in the provenance check; altered
months/days still fail, and monetary amounts and durations are unchanged.

The saved source reading and 66 retained authored paragraphs pass offline source
validation after this correction. The tenth theme was not yet authored. Offline
validation does not certify semantic review or produce a completed presentation.
The failed theme still needs an independent review on the next model run.

Replay any compatible saved introduction audit without model requests:

```powershell
python -m scripts.replay_introduction_audit "path/to/analysis_data.json"
```

## Reliability changes

| Reported issue | Resulting behavior |
| --- | --- |
| Capacity merged with output | Source measure qualifiers survive canonical series partitioning. Mappings that erase capacity or turn actual output into capacity remain unresolved. Trend execution rejects different source measures. |
| Group/company scope lost | Explicit column, merged-header, row and table scope declarations bind observations to retained entity/reporting-basis labels. Mixed scopes cannot silently enter a calculation. Unknown scope remains unknown. |
| Short substantive paragraphs omitted as layout | Paragraph length cannot certify layout. Nonblank layout needs literal header/footer or table-header evidence; otherwise its exact range goes through bounded re-reading. |
| Brief statements bypass meaning review | Every deterministically supported item goes through independent semantic review, including flat facts and qualitative statements. Unchanged reviewed items reuse their run-local verdict. |
| Failed introduction cached as completed | Results carry partial/complete state and a retry stage. Partial diagnostics stay inspectable but never enter the completed-result cache. Successful themes are separately source-verified and cached. Failed theme request caches are revoked. |
| Reanalysis reused another scope | Reanalysis takes a reviewed scope only when its scope key matches the current file, requirements and model settings. Orchestration also checks the source hash/page count. |
| One table exception skipped later pages | Exceptions are isolated by page, later pages continue, and the failed page retains its status and diagnostic. Incomplete table extraction is not cached as complete. |
| Encrypted PDFs reached model processing | Password-required PDFs raise an ingestion error before discovery, routing, requirement interpretation or model calls. Older cached encrypted metadata is also blocked. |
| Date axes rounded count labels | Calendar annotation receives the same count precision as the plotted labels, preserving every source unit after scaling. |

## Retry behavior

The first v126 run uses new extraction and analysis contracts. Later retries
retain successful request caches and verified themes. A retained partial
checkpoint skips discovery, observation semantics, and any completed candidate
scoring/calculations. Failed reading batches, outlines and themes revoke their
failed request caches while successful batches/themes remain reusable.
Failed or mismatched extraction checkpoints are not reused.
An explicit reanalysis still makes fresh model requests.

Verified-theme cache keys include literal source parts, source hash, purpose,
requirements, provider/model/endpoint, privacy, temperature and generation policy.
Source bindings and review digests are checked on reuse. API keys are excluded.
Local Only routing continues through the existing LLMGateway privacy checks.

Partial JSON/evidence remain available for diagnosis. A partial analysis cannot
be delivered as a completed PowerPoint. No saved failure is relabeled as success.

## Verification

`tests/test_analysis_reliability_v126.py` covers the nine boundaries, stale
encrypted metadata, failed theme cache revocation, verified theme reuse,
partial-result UI behavior, scope isolation, merged headers and resumed reporting.
Existing Brief fixtures now include an independent mocked reviewer; the complete
request ledger remains available. The offline latency benchmark records the two
additional review operations rather than concealing their cost.

Validation on this worktree:

- Complete offline suite: **3,624 passed, 8 skipped**. The four provider-library
  event-loop cleanup warnings do not represent failed document checks.
- Final row/header reporting-scope and extraction checks: **62 passed**.
- Reading/theme cache and gateway checks: **103 passed**.
- Saved analysis replay: no source-reading or retained-draft source failures;
  66 paragraphs checked, with one unauthored theme still pending.
- `git diff --check`: passed.

Streamlit widget tests ran outside the Windows sandbox because the sandbox
blocked their runner threads. Provider transport tests used mocked HTTP and a
locally cached public tokenizer vocabulary; no live model calls were made.

Pipeline contract: `2026-10-14-analysis-reliability-v126`.
Extraction contract: `extraction-v18`. Analysis contract: `analysis-v68`.

No live provider run, deployment, or successful new PowerPoint export is claimed
by the offline replay.
