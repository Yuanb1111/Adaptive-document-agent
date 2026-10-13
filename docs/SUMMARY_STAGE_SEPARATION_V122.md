# v122: independent content, format and pagination recovery

## Acceptance status at this checkpoint

This is an intermediate engineering checkpoint, committed at the user's request
before end-to-end concise-deck acceptance. It is not a claim that the reported
PDF generation failure is fully resolved.

Checkpoint regression: 3503 passed, 8 skipped, 3 dependency/event-loop warnings
in 329.40 seconds. Staged whitespace and credential-pattern checks passed.

The earlier live PDF run generated and rendered a 77-slide deck, but the user
rejected that length. The latest concise run still failed: its introduction
occupied six physical body slides against a five-slide allocation. Body-budget
repair preserved existing appendix copy but did not sufficiently shorten the
body. Exact paragraph selection and relocation remain follow-up work.

A final deck with 15–20 body slides, complete source/meaning and visual checks,
and a successful browser download has not yet been accepted. Do not use the
earlier 77-slide export or passing regression tests as a substitute for that gate.

## Implementation

The supplied v121 diagnostic failed after repairing a missing source part: the
corrected logical group contained five items, but the draft schema treated it as
a rendered slide with a four-item limit. That serialization failure spent the
last editorial attempt even though whole-item pagination could retain the copy.

Introduction authoring now uses logical content groups (up to 32 items per group).
The final slide model retains its four-item contract. Python paginates complete
paragraphs against the actual template geometry, preserving order, copy and every
source-fact binding. It never truncates text or drops a source part to fit a page.
An explicitly requested introduction slide budget remains enforceable.

Recovery has separate bounded responsibilities:

- Content repair corrects missing parts, unsupported claims and independent
  semantic rejections. Source checks and independent meaning review each retain
  one correction opportunity (at most three candidate drafts in total). A source
  repair therefore cannot exhaust the only chance to correct a later meaning
  rejection. An unchanged rejected draft remains an immediate failure.
  Global synthesis repairs return explicit paragraph replacements/additions,
  rather than a complete new draft. Python applies only the named logical item
  slots, preserving all untouched copy, bindings, identity and placement. This
  prevents attribution corrections from erasing previously accepted product
  details. Unknown, duplicate and unchanged targets fail closed; all final
  source and meaning checks still run over the complete result.
- Draft format repair gets its own bounded budget, with the invalid response,
  validation details and original source context. Exhaustion does not restart the
  editor. Privacy, transport and cancellation failures propagate immediately.
  Small string overruns (including the 601/600 boundary) use an exact-field model
  patch instead of regenerating every already valid field. Only the failing
  string paths may change; duplicates, unknown paths and evidence-ID edits are
  rejected. Full schema, source and meaning checks still follow. Larger overflows
  keep structural split repair; Python never truncates prose.
  Structural repair permits two draft calls. A targeted patch exposes each exact
  path and character limit in its response schema and may use the gateway's one
  format correction (at most three calls including the initial draft). Union
  alternatives with a conflicting placement are excluded from patch diagnosis.
- Pagination needs no model call to split oversized prose. Authoring transport
  permits 6000 characters, as in the existing editorial path; final slide items
  retain their 1200-character limit. Oversized paragraphs become exact sequential
  continuations sized against template geometry. Their concatenation digest,
  order, count and identical evidence bindings are verified. Numerical checks
  evaluate the complete original claim, so a split cannot detach a currency or
  unit from its quantity. Final source, coverage and meaning checks still apply.
  Exceeding an explicit physical body-page budget uses this layout budget too;
  it cannot consume the revision reserved for a later semantic rejection. The
  repair receives actual paginated counts rather than just logical group counts.
  For an authorized supporting appendix, budget repair returns only the new body
  and additions to existing appendix groups. Python retains all previous appendix
  paragraphs byte-for-byte. Layout correction cannot replace a reviewed data
  summary with a table-of-contents description or drop its existing evidence.
- Reviewer protocol repair continues to review the same generated slide and its
  exact ordered texts, independently of content editing.

The gateway's general format repair now includes actual failing field paths and
constraints. Exhaustion reports those paths and error types without including
source values in the error message. This also makes early source-selection
format failures actionable instead of reporting only `ValidationError`.

Selected reader paraphrases do not exhaust the source evidence. Compact authoring
and its independent reviewer now use each complete owned passage as their
citable evidence. Existing facts covering that passage are reused; otherwise
literal entries are appended as `evidence_only`, tied to the original part/page.
The original selective paraphrases remain in the reading audit. Complete-passage
entries still require authored copy and the normal checks. This preserves
qualifications beyond the reader's two selected facts and supports quantities
whose unit wraps onto another line, without asking the model to choose between
a narrow quote and a complete quote for the same source part.

Regression tests cover omission followed by a format failure and successful
six-item pagination, bounded format exhaustion, lossless paragraph splitting and
a format repair, exact copy/provenance preservation, and propagation of privacy,
transport and cancellation errors. Existing numeric evidence, review-target,
unit, explicit slide-budget and export guards remain active.

The real run exposed two additional boundary problems. Shared logical-group
titles now retain explicit source-fact references across pagination; title
evidence does not broaden an individual body's evidence. Numeric title checks,
unknown-reference checks and independent review still apply. Content repair
explicitly requests complete fact bindings when a quantity and its unit span
adjacent source quotes, rather than asking for an unchanged paraphrase.

Borderless tables now declare that `raw_cells` contains body rows, with headers
stored separately. Reconstruction therefore cannot mistake a section-only body
row for a column header and overwrite valid geometric amount/percentage roles.
The extraction cache version changes. Offline replay through extraction,
reconstruction and observation creation verifies that physical page 229 retains
alternating amount/percentage columns: `23,138` is scaled currency and `13.3`
is an unscaled percentage. Page 245 retains its count/percentage groups and page
264 retains date-header exclusion. Raw cells and source headers are preserved.

The first successful live export also exposed a length problem: independent
theme authors expanded 62 substantive Summary parts into 56 introduction slides.
A requested slide budget now takes a different editorial path: the introduction
is synthesized from the complete source context before any per-theme expansion,
with up to one third of the requested limit (at most five slides) allocated to
the body introduction. For an explicit body-only limit, the author may place
supporting context in an introductory appendix. It must synthesize related
passages rather than merely relocate an unchanged long introduction. The same
part-meaning, numeric and opening checks cover the combined body and appendix;
every substantive source part must still have independently reviewed visible
copy. Export checks fail if any required appendix item is missing. Without an
explicit body-only limit, this placement is rejected. An impossible allocation
fails visibly rather than dropping material. A length
requirement is also included in the trusted authoring instructions.
Global synthesis and its review use separate operation identities that retain
configured provider reasoning defaults; the small-theme reasoning reduction does
not apply to this cross-source editorial task.
Targeted revisions use the configured small-task reasoning policy and an 8000
output-token ceiling. This bounds local corrections without changing global
synthesis or independent review, following an observed 65536-token truncated
repair response during real acceptance.
The budgeted body and supporting appendix have explicit placement schemas.
Body copy targets 280-character paragraphs, but uses the same 6000-character
transport capacity as supporting copy. Actual geometry and physical slide
count, rather than an arbitrary extra string limit, enforce the body allocation.
A long paragraph cannot silently become an appendix item without the explicit
placement and user-authorized scope.

Slide limits distinguish `all` (the backward-compatible default) from an explicit
`body` scope. The exporter marks generated evidence-appendix pages in the native
slide metadata, so the reported body count survives saving and reopening the
PPTX. Cover, contents, closing and unmarked pages count toward the body budget;
only explicitly generated appendix pages are excluded. This is a layout policy,
not a document-type or issuer-specific workflow.
