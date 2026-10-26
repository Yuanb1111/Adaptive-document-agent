# Introduction layout choices v191

The reported v190 run passed discovery and failed at `introduction_editorial`:
the introduction budget was five physical slides, but pagination produced six,
then seven, then seven. The first rewrite merged a group that had fitted the
native three-column layout; the last rewrite repeated the overflowing draft.
Fewer paragraphs were not sufficient to reduce the physical page count.

When an audience-selected draft still exceeds its budget and the first layout
rewrite makes no measured progress, the final existing repair round can now
offer measured lossless choices. Each option combines all paragraphs within an
existing authored group, retaining its title, first heading, every subsequent
label inline, every word in order, fact IDs and exact original meaning quotes.
Python measures both alternatives through the normal paginator. It offers a
menu only when the alternatives can satisfy the current physical budget.

`SummaryLayoutChoice` goes through `LLMGateway`. The model judges whether each
combination is coherent using current copy, selected meanings and owned source
passages. It can retain the original layout. Python applies only the offered
option, and the ordinary source, quantity, authored-coverage and fresh independent
meaning-review gates still apply. This choice is not semantic approval.

The selector replaces the second rewrite, with no additional repair rounds or
format retries. Impossible menus retain the existing bounded rewrite behavior;
refusal, invalid output or remaining overflow fail transparently. The page cap,
font sizes, protected identity, Local Only rules and additive-repair restrictions
are unchanged. No source-specific titles or document types are special-cased.

Offline replay of the reported diagnostic reproduced all three page counts and
found five-page alternatives without structural coverage or geometry errors.
The native PowerPoint generation path also produced exactly five slides for the
candidate from the first failed rewrite. No live model was called, and this does
not certify independent semantic acceptance or end-to-end export completion.
The private diagnostic remains read-only and is not committed.

Reproduce the geometry and binding checks with:

```text
python scripts/replay_summary_layout.py path/to/analysis_data.json
```

Regression tests cover bounded selection, literal text and evidence preservation,
model refusal, impossible menus, missing meanings, cancellation, invalid options,
Local Only mock gateway routing and entry into fresh independent meaning review.
The pipeline version is v191; extraction and analysis cache versions are unchanged.

Validation: 1,017 related regression cases pass; six optional rendering cases are
skipped. Eight cases initially hit missing/unwritable local temporary directories;
all eight pass when rerun with a writable workspace temporary directory. Native
generation checks page count and literal visible copy, not a visual screenshot.
Python syntax and `git diff --check` also pass.
