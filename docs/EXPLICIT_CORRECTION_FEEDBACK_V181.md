# Explicit correction feedback (v181)

Two different inputs failed under v180. The checkpoint ending `.025` failed in
introduction editing; `.630` failed while reading source pages 16 and 17. Both
were complete structured responses rejected by evidence/protocol checks.

In `.025`, an independent reviewer found an assertion assigned to a passage that
did not support it. The resolution response said it had corrected the assertion,
but returned empty edits, additions, inclusions and referenced meaning IDs. Its
explanation did not change the current draft, so rejection was correct.

The resolver now distinguishes this unapplied-correction error and permits one
complete regeneration with the exact finding ID, required current meaning ID,
validation error and rejected proposal. Full original source and immutable current
IDs remain available. The rejected proposal is marked as untrusted diagnostic
data, never evidence. Both responses are retained in `protocol_attempts`; Python
does not extract replacement copy from the model's explanatory reason. The second
proposal must pass all existing ownership and mutation checks, then a fresh
independent semantic review. Other ownership, evidence, privacy and transport
failures do not enter this new retry. Cancellation stops before the second request.
The existing complete-response capacity retry remains bounded separately.

In `.630`, the model repeatedly grouped standalone source-note labels with page
layout. Mechanical evidence proved the running margin text and blank lines, but
not the labels inside the page. Even the final targeted response acknowledged
those labels were unproved and still returned `role=layout`.

Reading feedback now supplies each source line's `allowed_roles` at the first
general correction and both existing targeted correction opportunities. A line
without mechanical layout proof can be considered heading or content, not layout.
Instructions explicitly distinguish standalone section labels from substantive
notes and ask the model to partition mixed ranges. The model still decides the
semantic classification. No keyword-based relabeling, automatic content promotion,
source deletion or weaker layout validation is introduced. Reading's existing
request bound and exact accepted-line ownership remain unchanged.

Offline replay of the original `.025` response verifies that it is still rejected
and produces exact corrective feedback before requesting a new proposal. Replay
of all four saved `.630` responses verifies the new line constraints at each
correction and still rejects the invalid final layout. Neither replay makes a
provider call or fabricates a successful analysis. Synthetic tests additionally
exercise valid corrections, repeated failures, preserved accepted evidence,
cancellation, privacy errors, and final independent acceptance/rejection. The two
documents have not been rerun with a live model; improved feedback is not a
guarantee that a future model response will pass every downstream review.

The pipeline version is `2026-10-23-explicit-correction-feedback-v181`.
Extraction and numerical-analysis contracts remain v23 and v88. Load the new app
version before retrying; successful unchanged analysis caches remain reusable.
