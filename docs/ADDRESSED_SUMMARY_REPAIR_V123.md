# v123: explicit summary edit addresses

The v122 checkpoint retained an unresolved concise-deck acceptance failure.
Real PDF runs exposed two address ambiguities: body allocation confused existing
appendix paragraphs with body candidates, and content repair used rendered slide
positions as logical draft indices.

Body allocation now returns a required destination for each explicit paragraph
ID. The response schema enumerates only existing appendix destinations, rejects
unknown IDs and enforces the body selection count. Python retains or relocates
each original paragraph exactly once. Text, labels, identity and fact references
are copied unchanged. Physical pagination and the final body budget remain
independent checks; paragraph count alone is not acceptance.

Content repair receives an explicit editable-group/item catalog and original
source evidence, without the competing rendered-page address list. Replacement,
addition and title targets are schema-enumerated. Source facts carry their exact
quote and PDF pages directly rather than requiring a second quote-reference
lookup. When supporting appendices are
authorized, new supporting paragraphs target those appendices. Unknown targets
are format failures rather than silently redirected edits. All final source and
meaning checks still apply, including the generated opening's exact identity.

A meaning correction may introduce a citation error after source checks already
passed. That correction now has one bounded source-fix opportunity followed by
another independent meaning review. One additional meaning correction is allowed
only if the number of rejected source parts strictly decreases; opening-only
failures or non-improving review results cannot use it. The whole operation is
bounded to five candidate drafts, two source corrections and two meaning
corrections. Repeated drafts and unresolved final errors still fail.

The extraction and analysis cache contracts are unchanged. Updated model schemas
and prompts distinguish the changed operations; the loaded pipeline marker is
v123 so UI/export diagnostics distinguish this follow-up from the v122 checkpoint.

## Acceptance on 2026-10-13

- Regression suite: 3511 passed, 8 skipped, 4 dependency/event-loop warnings.
- Original supplied PDF completed the real DeepSeek pipeline through
  `LLMGateway`; valid prior extraction/model cache entries were reused. No
  fabricated responses, manual analysis patches or forced export were used.
- Native export: 47 slides, comprising 16 body slides and 31 appendix slides.
  The explicit body limit was satisfied after saving and reopening the PPTX.
- All 62 substantive Summary parts from source pages 10–21 passed independent
  meaning review and appeared in native exported evidence bindings. This does
  not assert exhaustive analytical coverage of every page in the entire PDF.
- Evidence and automated layout checks passed. All 47 rendered slides were
  individually inspected for fit, clipping and overlap.
- The production download component generated the PPTX in the local browser.
  Its download button was actually clicked. The downloaded package passed ZIP
  integrity, reopened successfully and matched the CLI export's slide text,
  geometry, tables, chart values and placement. Native coverage remained 62/62.
- Downloaded artifact: 880126 bytes; SHA-256
  `d5331fd9b6d0706dabc966c2c2b2238f6172589c384356ea8275a76b4fb54e74`.

Two pre-existing editorial findings remain visible: omitted-evidence analytical
coverage has not been fully reviewed, and ambiguously bound takeaways were
withheld. These are report-review limitations, not a failed opening or broken
download. The output remains a reviewable report draft, not a certification that
every analytical conclusion or source section is complete.
