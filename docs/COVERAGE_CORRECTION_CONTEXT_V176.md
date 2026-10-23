# v176 complete-source coverage correction

The saved `analysis.402` run completed the company introduction successfully.
Its presentation coverage review checked all 491 candidates in eight batches,
then proposed 94 additions for a final merge. The merge's `FY and 6M views`
caveat hit the conservative numeric-token validator. The intended correction
could not be sent: the complete source plus the rejected draft and diagnostic
exceeded the 120,000-character input budget.

Coverage correction now first tries the existing complete-source request with
the full rejected response. If that is too large, the same single correction
regenerates a complete response from the unchanged original input and full
validation diagnostic. The rejected response remains verbatim in the audit,
identified by a SHA-256 reference in the request. The model is explicitly told
that the omitted rejected draft is not approved and that a patch is insufficient.

No source fact, qualification, user instruction, accepted observation or requested
decision ID is removed. The new reply must pass all existing source, numerical,
period, inventory and immutable-selection checks. Repeated invalid output still
fails. Transport, privacy, cancellation and truncation handling is unchanged.
If even the original source and diagnostic cannot fit, the review still fails
closed. Framing and the correction instruction count toward the input budget.

Offline replay of `.402` measured 141,770 characters for the full rejected-copy
request and 116,779 for the complete-source regeneration request. A simulated
reply making the period context explicit passed the ordinary merge checks for
all eight topics and 94 decisions. This is transport/validation replay, not a
real model judgment or a completed pipeline rerun. The saved artifact is unchanged.

Synthetic tests cover both correction modes, schema-invalid raw responses,
unchanged complete source, retained rejected audits, repeated rejection, privacy
and transport failures, and an input that still cannot fit. The presentation
contract is `2026-10-23-coverage-correction-context-v176`; extraction and analysis
cache contracts remain unchanged.
