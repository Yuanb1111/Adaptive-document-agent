# Presentation planning stalls and interrupted sessions (v80)

The hosted progress log stopped after `slide_plan` started. An offline replay of
a previously saved analysis reproduced a CPU stall without any model request:
after 45 seconds, the stack was still in `PresentationPlanValidator._money_spans`,
called while validating source-page numbers during topic-plan compilation.

The suffix-currency regex could begin at every whitespace character, then split
the same whitespace between overlapping optional groups. Long PDF layout spaces
therefore caused cubic backtracking. A separate optional closing-parenthesis
pattern also allowed repeated whitespace partitioning before a currency suffix.
This can monopolize Python execution and interfere with server responsiveness;
the available hosted log does not prove a process restart or the precise cause
of every browser disconnect.

Money matching now begins at a number, sign or opening parenthesis for suffix
currencies, and uses non-backtracking whitespace consumption. Period handling
also skips money-span discovery when there is no duration token to disambiguate.
The implementation does not collapse source whitespace, merge separate numeric
values, change evidence, or skip provenance validation. Python 3.11+, already
required by the project, supports the possessive regex quantifiers used here.

The same offline topic compilation completed in 11.263 seconds after the fix,
producing 15 planned slides. This measures compilation on the local machine,
not a complete cloud analysis or an online model call. Source-derived inputs
remain outside tracked files.

Regression coverage includes long spaces, tabs, line breaks and nonbreaking
spaces, currency-prefix/suffix near misses, valid compact monetary amounts,
accounting signs, interim periods, and separate values on adjacent lines. The
long-input test runs in a subprocess with a generous deadline so a recurrence
cannot hang the entire test process.

The Streamlit entry point also records each active attempt before writing UI
progress. A same-session rerun cannot start the same document/settings again
while that attempt is active, including through force/retry. Stop/rerun control
exceptions still propagate, but leave an interrupted record for the existing
explicit retry action. Ordinary failures are saved before rendering error UI,
and completed results remain reusable if final status rendering is interrupted.
Attempt IDs and stages are logged without PDF contents or credentials.

This guard preserves public-session cache isolation. It does not recover a new
session after browser reload or a killed server process, and does not introduce
shared caches or background jobs. New hosted logs are still needed to distinguish
those events from a same-session interruption.

Validation: 731 presentation/claim/topic/pipeline tests and 36 session/startup
tests passed. The latter include real Streamlit 1.65.0 UI checks with the hosted
deployment's pyarrow 24.0.0. A separate bounded differential comparison of
11,200 amount/period strings returned identical numeric tokens before and after
the regex change.

The pipeline cache version changes to v80. Extraction and analytical model
cache contracts remain unchanged.
