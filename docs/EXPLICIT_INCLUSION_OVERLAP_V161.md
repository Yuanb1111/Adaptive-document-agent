# Explicit inclusion overlap (v161)

The v160 checkpoint ending `.768` stopped at `introduction_editorial` with
`Meaning resolution addition must identify each affected included part at most once`.
This was a different failure from the v160 chart-topic export issue. The model
returned nine edits for twelve findings, plus an explicit inclusion for a previously
omitted part. It also repeated that inclusion's exact required meanings in additions.
The old validator rejected additions targeting a previously omitted part even when
the same response explicitly included it with identical copy and a selection reason.

Inclusions are now validated before additions. An addition can be coalesced only
when it has the same exact part ID and identical ordered RequiredMeaning objects
as an eligible, explicit inclusion. Equality includes the proposed evidence strings;
there is no semantic matching, rewriting, union of differing claims or implicit
inclusion. Duplicate entries within either list, unowned parts, absent reasons,
conflicting copy and incomplete finding dispositions still fail. An inclusion must
resolve an explicit corrected finding. Unaffected decisions and source text remain
unchanged.

The original model response remains intact. Successful protocol audits identify
`coalesced_inclusion_addition_part_ids` and retain `semantic_approval=false`.
The existing independent full-source review must accept the corrected selection;
the structural repair alone never marks the introduction or pipeline complete.
The prompt now explicitly separates additions to already included parts from new
inclusions and asks the model not to repeat an inclusion in additions.

The extraction contract remains v23; the analysis contract advances to v85.
Restart the app to load v161. The failed checkpoint still requires fresh semantic
review and subsequent reporting/export before it can produce a completed deck.

Use `python -m scripts.replay_meaning_resolution <analysis.json>` to replay the saved
response through the production resolution function without provider requests.
This reads the saved source, decisions, findings and raw response unchanged. It
checks explicit inclusion wording/reasons and reports protocol validation only;
it does not fabricate a completed output or semantic acceptance.

Validation of the original `.768` response passes the production protocol with
twelve findings, nine edits and one explicit inclusion. The saved response stays
unchanged and no provider request is made. The focused regression suite passes
96 tests, including exact-copy coalescing, conflicting claims/quotes, invalid or
missing inclusions, duplicate addresses, complete finding ownership, raw audit
preservation, saved-response replay and fresh semantic acceptance/rejection.

The full Windows suite completed with 5,077 passed, 14 skipped and 11 environment
failures. Eight failures came from subprocesses missing the temporary dependency
directory; three mocked provider tests attempted to load uncached tokenizer data.
After propagating PYTHONPATH and preloading the standard tokenizer vocabularies,
all 154 tests in the four affected files passed, covering all eleven failures.
Four dependency/event-loop warnings remain. An earlier sandbox run was interrupted
after Windows temporary-directory permission failures; the reproduced cases passed
outside the sandbox. No product changes were made to bypass any of these checks.
