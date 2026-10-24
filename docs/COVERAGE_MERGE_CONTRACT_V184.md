# Coverage merge decision ownership (v184)

The recorded v183 run stopped at `presentation_coverage` before assurance review,
final briefing and export. All 494 candidate series had completed eight independent
review batches. The final synthesis requested decisions for 117 proposed additions
but returned 118 twice: an already accepted operating-cash-flow series received an
extra omission decision whose reason misidentified it as investing cash flow.
The v183 exact-ledger validator refused both responses. No PowerPoint export
attempt was recorded; the original diagnostic file remains unchanged.

## Change

The final merge now receives a request-specific `TopicCoverageReview` schema. Its
decision-ID enum contains only the provisional IDs, and its ledger length equals
the requested count. A bounded compatibility path quarantines extra decisions only
when their IDs belong to the immutable original topic selection. Their raw decisions
and reasons remain in the merge audit but have no authority over proposed additions
or report copy. The merge can proceed only after all original observations remain
represented and every ordinary source, period, quantity and topic check passes.
This handles complete responses from providers that do not enforce the wire schema.
No model-authored proposed inclusion or omission is changed by this scoping step.

Unknown IDs, missing requested decisions, duplicates, blank reasons, lost accepted
observations and unsupported topic claims still fail. An `accepted_decision_echoes`
record is written only after successful validation, alongside the complete raw
response. Python does not decide analytical importance or trust a mistaken reason
attached to an out-of-scope echo.

The single correction explicitly distinguishes removing an invalid ledger entry
from removing accepted source evidence. It retains full source context and does
not treat rejected omission wording as evidence. Repeated failure stays unresolved.
The completion error now carries the original bounded coverage diagnostic, including
structured schema errors, instead of reporting only an incomplete/stale review.

The operation name, reasoning policy, gateway routing, privacy checks, model-call
limits and output budget remain unchanged. The scoped schema participates in the
existing gateway cache key. Extraction and unrelated model caches remain reusable.

## Verification and limits

- Both recorded merge responses now pass offline merge replay without rewriting
  the saved reply: 118 raw decisions, 117 provisional decisions, one quarantined
  accepted echo, six topics and all 65 originally accepted observations preserved.
  The saved diagnostic file has not been changed or relabelled complete.
- Synthetic gateway tests cover accepted include/omit echoes without an extra call,
  successful correction of unknown IDs, repeated invalid output, lost source facts,
  false inclusion, duplicate/missing decisions, blank reasons and invented periods.
  Full source context, raw responses and the one-correction limit remain intact.
- The final 305-test regression selection covers merge contracts, independent deltas,
  completion gates, correction capacity/encoding, source binding, v183 evidence,
  gateway privacy and operation-level reasoning/cache behavior.

No live-provider rerun or PowerPoint export has been completed for this incident.
Restart with this workspace's v184 code and retry reporting to obtain fresh model
decisions and complete the remaining assurance, briefing and export checks. Schema
constraints improve the contract but cannot guarantee every future model response.
