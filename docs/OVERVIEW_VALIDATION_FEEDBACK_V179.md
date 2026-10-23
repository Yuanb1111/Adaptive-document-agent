# Discovery overview validation feedback (v179)

The reported 45% failure occurred while merging selected sections into the global
document profile. The downloaded model-call ledger confirmed 22 successful calls,
followed by two `DiscoveryOverview` calls marked `invalid_format`. Both ended with
`finish_reason=stop` (445 and 328 output tokens). This rules out output truncation
and transport failure for those calls. The historical CSV contains neither raw
responses nor validation paths, so the exact failing fields cannot be recovered
from it. No specific field failure is claimed as the incident's proven cause.

Overview synthesis already allowed one compact regeneration, but its feedback
only said the schema was invalid. The retry now receives the exact schema paths,
error types and constraints while retaining all original page-bound summaries.
Invalid output is not sent back as source evidence; a truncated prefix is never
continued. Page integers, field lengths and all other schema limits stay strict.
The existing two-call bound and successful chunk/overview cache reuse remain.
Transport/privacy failures do not enter this content correction. Provider-filtered
output does not trigger regeneration.

If synthesis still fails, the user-facing error names the operation and failing
fields. A session-owned diagnostic JSON download retains both rejected responses,
field diagnostics, pipeline version and basic response usage. Raw model output
is not printed in the normal error or application logs, and no API settings,
credentials or raw SDK response object are included. The download explains that
its contents derive from the user's document. It does not mark the analysis as
complete or trigger another model call.

Tests cover precise feedback for excessive prose, wrong page types, excessive
list length and extra fields; immutable source context; the two-call bound;
failure publication/download; cache reuse; and existing truncation recovery.
These are offline contract tests, not a live rerun of the reported document.
