# Presentation evidence corrections (v44)

The fixes apply to source structure and explicit metric/unit evidence, not to a
particular issuer or document type. They add no model calls.

- A numeric column's `amount` classification alone is not proof of currency.
  Explicit count rows take precedence over table currency defaults. Monetary
  units declared on an individual row remain local to that row. Contradictory
  count and currency evidence stays flagged rather than silently discarded.
- Unit parsing and presentation retain explicit denominators such as `/unit`.
  Price/rate appendix rows use their reported scale and raw cell values, while
  charts retain normalized values and label the denominator.
- Expense ratios are shortened to `/ revenue` only when the source label or
  its own row/column supplies that denominator. Bare ratios and qualified
  denominators keep their source meaning. Normalization also repairs legacy
  display labels without changing raw data or evidence.
- Resolved company identity appears on the cover and Summary introduction,
  with source pages retained. Contents entries wrap and paginate without
  silently removing their final words.
- Completed-result cache keys include the pipeline version. Model-request and
  table-extraction cache versions remain unchanged, so compatible intermediate
  work can still be reused.

Regression fixtures are synthetic. Local offline replay uses the retained
source tables and existing semantic selections, then passes through the normal
financial and rendered export gates. Source documents and replay artifacts are
kept outside version control. Offline replay does not measure a fresh model
run's cost or latency, and previously downloaded files do not change in place.

Verification: 1,232 tests passed and three platform/opt-in integration tests
were skipped. The local 19-slide replay passed financial and rendered QA; all
14 native charts retained their 48 numeric values, and all changed observations
retained their raw values and page-level evidence. Every rendered page was
visually inspected. No cloud/model request was made for the replay.

After deploying, restart the application when source reloading is disabled and
rerun analysis. The displayed pipeline should be
`2026-09-28-evidence-unit-labels-v44`.
