# Physical-budget recovery trigger v192

The reported v191 failure did not call `SummaryLayoutChoice`. Its physical page
history was 6 -> 6 -> 6 against a five-page limit. The first rewrite reduced
estimated occupied height from 27.593056 to 24.802222 inches, so
`compression_progress.improved` was true. The v191 controller required that flag
to be false before offering measured choices. Consequently the last round
repeated a full-page rewrite, which returned the same overflowing draft.

This was a control-flow defect in v191. The previous offline candidate replay
called the choice generator directly and therefore did not test that controller
condition. Existing tests covered completely stalled geometry, but missed shorter
copy which still occupied too many physical pages.

The final selected-audience repair now evaluates the measured alternatives whenever
pagination is still over budget, irrespective of incremental height/page progress.
An evaluation record preserves current and target page counts, candidate groups
and whether a feasible menu exists. Already-fitting drafts return immediately;
impossible menus use the existing bounded rewrite. No retries or page allowances
are added. Evidence, protected identity, source/quantity checks, model refusal and
fresh independent semantic review retain their previous behavior.

The replay tool now offers `--repair-path`, which invokes the actual
`paginate_draft` controller through a Local Only mock gateway using the recorded
initial draft and first rewrite. The selector response is explicitly simulated;
this is not live model approval or an end-to-end analysis result.

```text
python scripts/replay_summary_layout.py path/to/analysis_data.json --repair-path
```

Both reported diagnostics pass this control-flow replay: v191's 6 -> 6 -> 6
becomes 6 -> 6 -> 5, and v190's 6 -> 7 -> 7 becomes 6 -> 7 -> 5. Both invoke
`SummaryLayoutPages`, then `SummaryLayoutChoice`, preserve structural evidence
bindings and produce five slides through the native PowerPoint generation path.
No private source or diagnostic is copied into the repository.

New regressions exercise real geometry for unchanged page counts with lower
occupied height, reduced page counts still over budget, and immediate return when
the first rewrite meets its budget. The pipeline version is v192; extraction and
analysis cache versions are unchanged.

Validation: 194 related tests pass, including the v191 preservation/refusal and
independent-review checks. Python syntax checks and `git diff --check` pass.
