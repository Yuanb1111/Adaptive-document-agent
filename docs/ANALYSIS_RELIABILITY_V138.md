# Distinguish authored proposals from canonical evidence during review

The selection author leaves `source_quote` empty; Python fills it from the
complete owning source passage before independent review. The reviewer formerly
inherited the author-only empty-field instruction, creating a conflict when
reviewing correctly populated canonical evidence.

The author-only instruction is now applied only to selection generation and its
bounded authoring retries. Review explicitly expects Python-bound source quotes
and still checks every assertion, attribution, qualifier and omission against
the original source. Proposed model quotations remain diagnostic data and
cannot replace canonical evidence. No source or semantic validation is relaxed.

Regression checks verify both role-specific prompts, exact source binding,
rejection of unsupported meanings, and the existing bounded meaning repair.

An unrelated claim-recovery blocker is also removed: when page-local period
checks filter an unsafe selection reason, the continuation now retains its
question and uses the existing literal metric/period evidence inventory instead
of an empty reason. The original model rationale remains in the topic/theme.
This permits strict question-first claim recovery and the existing bounded LLM
wording correction to run; it does not invent missing endpoints or waive any
claim, period, source or plan checks.

An offline replay of the affected v136 result retained all six selected topics,
compiled a topic-based plan instead of the degraded fallback, and left zero
claim-validation errors. The ambiguous net-assets/liquidity takeaway remains
withheld for the existing model correction step. The original input file was
unchanged. This replay made no model calls and does not establish that a fresh
independent introduction review or end-to-end export has succeeded.
