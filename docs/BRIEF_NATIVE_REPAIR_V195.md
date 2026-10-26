# Brief native quantity repair v195

The reported v194 diagnostic ending `.770` fails at `executive_brief`, not
`report_audit_scope`. Recorded wall time is 637,356 ms. Its summary initially
rounded several source-native amounts and mixed positive loss magnitudes with
negative table coefficients. The source validator correctly rejected those
unbound representations.

The residual source writer then returned exact signed native quantities and
explicitly selected the obsolete annotations for removal. The removal guard
incorrectly required the old annotation's shown coefficient and scale to already
match its source coefficient. For example, an old rounded million-unit annotation
containing a native thousand-unit source coefficient could never satisfy that
test, even after the model replaced the text with the exact negative thousand-unit
amount. Three valid source corrections were rejected for this reason; only one
of the four targeted items survived.

## Removal contract

Removal remains an explicit model action by exact existing annotation index.
The old positive quantity must no longer be displayed, and its declared negative
coefficient must match both a literal item-owned native quantity and the revised
displayed negative amount, with the same currency. A valid old mapping retains
its original native unit. A malformed old mapping requires a unique native unit
for that coefficient; ambiguity is rejected. The deleted mapping is not used to
authorize rounding, conversion, sign changes or new facts.

All revised copy still passes the complete source validator. Missing, invented,
wrong-currency, wrong-scale, rounded and unsigned replacements remain rejected.
No metadata is automatically removed without a model selection. Existing literal
quotations, raw document data and retained observations remain unchanged; fresh
independent meaning review is still required after source acceptance.

The diagnostic also contains an inconsistent comparison-review correction:
the reviewer removed every comparison but retained `numeric_comparison=true`.
The schema description and correction instructions now explicitly require the
model to reassess that flag alongside the comparison list. The deterministic
gate still rejects true with no endpoints. False does not bypass the independent
audience reader: an omitted directional assertion remains an error. This prompt
clarification is not proof that a new model run will return a valid review.

## Offline verification

```text
python scripts/replay_brief_source_repair.py path/to/analysis_data.json
```

Replaying `.770` with its actual recorded source-correction response now accepts
all four targeted items (indices 0, 1, 2, 3), rather than only index 1. The entire
five-item brief has zero remaining source-validation errors. The script verifies
that source pages, observations and input copy are unchanged, makes no provider
calls and never claims semantic approval or end-to-end completion. It reads the
private diagnostic in place without copying it into the repository.

Regressions cover malformed mixed-scale annotations, exact native replacements,
source/currency/unit/sign preservation, ambiguous native units, explicit removal
selection, unchanged siblings, and independent direction review after comparison
flag correction. Existing full repair-flow tests still require a fresh independent
meaning verdict and preserve rejection. No repair budgets are increased.

The pipeline version is v195. Extraction and analysis cache contracts are unchanged.

Validation: 1,206 related brief, audit, gateway/reasoning and cache regression tests
pass across two disjoint selections. Python syntax checks and `git diff --check` pass.
