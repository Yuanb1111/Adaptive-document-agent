# v205: exact audit navigation and source-bound corrections

The v204 export ending in `105212.985.json` failed before evidence review:
the discovery model dropped two characters from a persistent observation ID.
The generic correction repeated the same unknown ID and exhausted its budget.

Discovery requests now use short request-local target and section references.
Python resolves them through an exact, recorded map to the retained identities.
Unknown references and duplicate resolved identities receive field-level errors
and the allowed references. No fuzzy matching, dropped targets, changed source
pages, automatic assurance or additional correction attempts are introduced.
Stored selections and subsequent evidence reviews still use canonical IDs.

With the user's permission, real DeepSeek validation exposed further failures
after discovery. The fixes keep the original evidence requirements:

- Continuous snapshot headers may include titles, units and qualification rows
  around their contiguous date/year tiers. Intervening prose cannot be skipped.
- A reviewer-owned page-label typo returns to the reviewer within the existing
  one-output-correction budget. It does not consume a writer semantic correction.
- Target-page restrictions apply only to the original target quotation. A
  counterpart can come from another supplied page, but must have the literal
  same measure and amount within the claimed assurance scope. Summing component
  rows cannot create an audited counterpart.
- Unit mismatch feedback treats both model fields as editable proposals rather
  than demanding invented source text matching the model's normalized spelling.
- The unknown-disposition review explains its source reasoning before returning
  its acceptance boolean. Acceptance means the unknown is justified, not that
  the observation is audited. Python never flips the model's verdict.
- Meaning-only briefing correction receives an explicit inventory of quantities
  already displayed in each editable item, including their original signs and
  scales. This gives a requested wording repair explicit alternatives to rounded
  million/billion replacements. The existing source and semantic gates still
  reject changed amounts; correction budgets are unchanged.
- Physical-budget correction retains the discarded candidate's full source-row
  review diagnostics. Its one subsequent proposal now sees the actual rejected
  measures and reasons rather than only a generic semantic-review error.
- A meaning correction can change the rejected item's label as well as its body.
  Previously a false heading could remain locked while only its body was
  repairable. Unaffected items, evidence, order and title remain locked. Numeric
  locks now cover both editable fields and independent meaning review still runs.
  Direction review also distinguishes factual comparisons from explicit change
  assertions without calculating a direction from displayed numbers.

Private source files and live diagnostics remain outside version control. Live
tests use LLMGateway, the existing configured provider and explicit user consent.
The original download and retained raw observations are checked for mutation.

## Validation

Synthetic tests exercise exact reference resolution, collisions, duplicate aliases,
bounded correction, multi-range targets, headers with surrounding unit rows,
repeated page-label failures, source-page restrictions and unit feedback.
Focused regressions: **378 passed, 5 skipped**. Skipped cases require external
checkpoint fixtures. Live audit continuation passed all four evidence groups.
A separate run from the original `.985` file, without any accepted diagnostic
batches, also passed all four groups in **40.1 seconds / 10 physical model calls**.
Unsupported amounts retain unknown assurance. Reporting/export results
are recorded below. These are continuations of saved extraction,
not fresh PDF-to-analysis benchmarks or guarantees about future model output.

The first live reporting continuation passed physical selection and independent
omission review, then failed because a meaning correction rounded signed source
quantities. The added quantity inventory is covered by **121 passing briefing
contract tests**. No export was accepted from that failed attempt.

The second continuation exposed discarded source-row review feedback during
budget correction. The feedback-retention fix passes **196 budget regressions**,
including repeated rejection and reviewer exception cases; failed candidates
remain unapplied and raw observations remain unchanged.

The third continuation exposed a false loss-direction heading locked during its
meaning correction. The label repair adds no model request or approval shortcut.
The briefing suite ran 694 cases: 692 passed initially and two new fixtures were
rejected as duplicate findings before their intended assertions. After correcting
those fixtures, all nine tests in their module passed. The other 692 cases needed
no implementation or expectation changes.

## Completed live reporting verification

The final continuation used the audit result regenerated from the original `.985`
export. It passed physical-budget selection, independent source/omission review,
executive briefing, supplementary-source integration, customization/localization,
the production completion gate, financial evidence QA, native PowerPoint preflight
and strict local rendered layout verification. No `force` flag or mocked review
was used. Reporting and export took **355.2 seconds / 31 physical model calls**.
The verified file has **19 slides: 18 body slides and one data-index slide**,
within the requested 20-slide body cap. Reloading the serialized result passes
the production completion gate, and every retained observation and source page
matches the original `.985` data exactly.
The result JSON and verified PowerPoint remain in ignored local diagnostics;
neither private source content nor provider credentials are committed.
