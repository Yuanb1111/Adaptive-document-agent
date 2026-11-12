# .813: incomplete source-authored selection output

The November 12 `analysis_data - 2026-11-12T131855.813.json` checkpoint
stopped at `presentation_selection` after 626.400 seconds. The source-authored
selection call sent 103,154 input tokens and exhausted its 12,000 output-token
limit. The saved response was empty, and its provider finish reason was length.
This is output truncation, not a successfully parsed selection or PPTX export.

Source-authored analysis selection now starts with 24,000 output tokens and
uses the existing bounded-capacity helper to retry once at 40,000 only when
the provider explicitly reports length truncation. Both calls receive the
same complete messages, schema, source evidence and semantic reasoning policy.
Partial output is diagnostic data only. It is never parsed, continued, merged,
or treated as source approval. The ordinary shared 900-second deadline,
privacy checks, transport behavior and independent reviews remain in force.
Invalid complete output retains its existing content-preserving format repair.

A localized copy defect can now use the existing two addressed corrections
from the initial proposal. It no longer forces an intervening full rewrite
of every selected page. Material ranking changes retain their separate bounded
priority correction. Copy-only review still cannot reopen settled priorities;
out-of-scope objections remain visible to the final independent review.

A source-identical reporting retry can also restore provisional findings and
the outline after this exact selection-generation failure. The current
document, profile, observations, tasks and calculation results must match.
This does not restore a partial selection, a presentation plan or a semantic
verdict. Selection, numeric binding, material-omission review and final
independent original-page review must still run.

Validation so far:

- 67 capacity, format, feedback and budget-output tests passed, including the
  actual private .813 checkpoint replay. One unrelated optional fixture skipped.
- The final broader retained/reporting-checkpoint suite passed 353 tests with 18
  optional external-fixture skips.

`scripts.run_live_checkpoint` runs the real provider-matched `LLMGateway`
without request caching. Its `--fresh` option uses the checkpoint solely to
verify the original PDF's identity, then starts ingestion with `resume=None`.
It records `live_fresh_pdf` separately from `live_reporting_resume` so the two
outcomes cannot be mistaken for each other. Live validation results follow.

The first continuation passed complete analysis selection at 431.491 seconds
and reached the briefing, using 36 real calls overall in 765.850 seconds.
It stopped at briefing validation: the source reviewer still required a
non-cash/non-operating cash-flow qualification and the separate current versus
non-current indebtedness movements. It did not time out and did not export
a PPTX. Its original evidence, findings, selected pages and introduction are
retained in `output/live-813-20261112-01/` for the next real continuation.

The third continuation passed the briefing but stopped on a nonliteral source
quotation assembled across table columns. The existing one-shot reference
correction now also handles this representational error. It offers only
premeasured exact source-reference IDs on the object's already-selected pages.
Python restores literal spans; conclusions, dispositions, amounts and original
source pages remain unchanged. The same correction budget is shared with
quote-capacity errors, and every repaired proposal still needs independent
source approval. Whitespace-only quotations also fail the literal binding.

The complete local regression run passed 7,023 tests with 39 optional skips.
The subsequent quote-binding/source-integration suite passed all 108 tests.

A first fresh-PDF run used two concurrent requests while running alongside
the continuation. It reached the shared 900-second deadline during selection,
after completing discovery, extraction and calculations. It is not a complete
report and did not export a PPTX. A second fresh run uses the application's
ordinary four workers and keeps the same original deadline. The deadline was
not extended or restarted inside either attempt. The ordinary four-worker run
completed extraction and calculations but stopped at page-copy validation after
608.911 seconds and 68 real calls. Its inventory and net-current-assets driver
sentences still lacked complete comparison scope after the bounded copy repair.
It did not time out, complete the report or export a presentation.

The fourth continuation exposed an invalid reference ID: a decision allowed
page 180, while the accompanying addition's existing scope allowed only pages
178–179. A complete reference response with literal-enum errors can now receive
one format correction for exactly those invalid fields. Valid sibling fields
remain unchanged; each corrected field retains its original page enum and quote
limit. Missing, malformed, refused, truncated or repeatedly invalid output does
not enter an unbounded repair. The restored literal proposal still requires
all independent source and merged-brief checks. The targeted tests passed 13
cases, and the preceding broader source suite passed 287 cases.

A later semantic rewrite repeated the same cross-column transcription defect
after consuming the existing reference-repair allowance. New full source drafts
therefore use a page/reference-pair schema: on numbered pages the model selects
only the measured `evidence_reference_options`, and Python restores the exact
continuous original text. The full supplied source remains visible to the
writer and reviewer. Existing literal checkpoints remain readable; an
unnumbered context or an individually oversized line retains literal-substring
validation rather than losing its source. Transport enums are converted to the
ordinary literal models before restoring evidence and comparison-table cells.
No disposition, claim, quantity, source page or independent verdict is generated
by this deterministic conversion.

The sixth continuation passed supplementary-source integration. Final independent
page review then required the literal annual/half-year parameters in the inventory
turnover method. It stopped at `presentation_coverage` after 162.503 seconds and
three real calls, without exporting a PPTX. The existing addressed copy-repair
path handles that reviewer objection on the next continuation.

## Verified .813 output

`output/live-813-20261112-09/` completed the real OpenAI `gpt-6-luna`
continuation and exported `analysis_presentation.pptx`. The final continuation
used seven real requests in 267.996 seconds, including addressed copy repair,
fresh independent original-page review and display-text review. It is a
checkpoint continuation, not an uninterrupted new-PDF run.

The native export and rendered QA passed without forced export or visual repairs:
18 slides, five editable native charts, valid ZIP, no reported QA issues.
Every slide was additionally rendered in installed Microsoft PowerPoint at
1600×900 and visually inspected. The original document, all 1,535 original
observations' raw values, normalized values, units, scales, periods, currencies
and page evidence, and all 20 calculation results remain unchanged.

PPTX SHA-256:
`c912556fd528ca3947fe046b65d215ee2613fc20af6d5faa4af67b57a13ef730`.
Private source, responses, outputs and credentials are excluded from Git.

The current source/retained-analysis suite passed 616 tests (13 optional skips).
Final-review/source-citation tests passed 66 (three optional skips). A complete
regression pass covered 7,079 cases: 7,029 passed, 39 skipped and 11 failed.
Eight failures were old literal-response fixtures incompatible with the new
reference-only writer transport; their full format-recovery module subsequently
passed all 15 tests. Three Gemini HTTP-mock failures came from an uninitialized
tokenizer attempting a download after the tests cleared the environment; they
passed with the existing offline tokenizer preloaded. A combined recheck of both
modules passed 152 cases, with one first-start Streamlit test exceeding its
three-second startup timeout; its isolated recheck passed (one test in 3.50
seconds). All eleven failures from the full pass have therefore passed their
subsequent focused rechecks; no single later full-suite run is claimed.

Additional fresh-PDF validation remains distinct. The third fresh attempt
completed extraction/calculations, then stopped on introductory reading format
validation (four facts where the source-reading schema permits two). Its
explicit checkpoint continuation retained that new extraction and progressed
through report selection, but reached the unchanged shared deadline during
local page revision. Neither is recorded as a completed fresh-PDF export.
