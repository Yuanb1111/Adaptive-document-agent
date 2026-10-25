# Discovery citation cardinality v190

The reported v189 failure occurred in `discovery / DiscoveryOverview`, before
presentation planning. Both complete JSON responses were rejected solely because
`document_summary_pages` contained 25 and 26 entries while the overview schema
allowed at most 24. Retrying the overview did not repair that arbitrary limit.

Citation count now follows the supporting source rather than a prose quota.
The schema retains strict positive integer page IDs, and the prompt asks for
distinct supporting physical PDF pages from the supplied chunk ranges. It does
not request unrelated pages. Existing discovery normalization still deduplicates
and intersects citations with reviewed ranges. Summary/point/quality-note prose
limits, the single repair attempt, provider routing and privacy rules are unchanged.
No citation is truncated to meet a count quota.

The pipeline version changes to v190. Overview cache identity already includes
the prompt and schema, so the changed contract gets its own key while successful
chunk discovery and extraction caches remain reusable.

Offline validation of both recorded responses preserves their complete page
lists and summary wording. This proves the reported schema failure is fixed;
the small failure diagnostic alone cannot independently prove source support or
completion of the remaining pipeline. No live model call or source upload was
used for the replay, and the private diagnostic is not committed.

Regression coverage includes 24/25/26/80 citations without retries, successful
cache reuse, invalid page types and bounds, unchanged prose limits, duplicate and
out-of-range removal, and preservation of source data and metric inventories.
The related discovery, routing, chunk recovery, pipeline, reasoning and privacy
regressions pass: 468 tests. Changed Python files compile and `git diff --check`
passes.
