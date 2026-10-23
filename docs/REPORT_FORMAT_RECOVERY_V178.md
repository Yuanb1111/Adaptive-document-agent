# Report format recovery and ratio endpoint ownership (v178)

The `.692` export ran v177 and stopped at `source_integration`. Its complete
`SourceIntegrationDraft` contained an added conclusion of 578 characters, above
the 550-character schema limit. The model ended normally. Source integration
requested the draft outside its existing correction handler, so this correctable
format failure became a terminal incomplete-report result.

The writer now routes complete schema failures through its existing one-correction
budget, shared with evidence and semantic corrections. The independent reviewer
has one format/section-ID correction across both writer attempts, retaining the
same complete original sources and draft. A substantive rejection still returns
to the writer; format recovery cannot discard it or grant approval. Exhausted
review format errors cannot borrow another writer attempt.

The adjacent assurance writer now handles schema failures within its existing
binding-validation correction budget. A shared diagnostic helper supplies exact
field errors, including nested field lengths, and retains raw output as untrusted
data. Audit source discovery reuses this diagnostic helper. Python never fills a
missing rationale, truncates prose/quotations, or silently accepts invalid output.
Transport/privacy failures do not trigger regeneration. Truncated output keeps
the existing capacity-only retry; provider-filtered output is not format-repaired.

The same export also contained a recovered presentation-plan warning: the phrase
`gross profit/revenue` was split into component metric labels, attributing the
39.1% and 43.9% endpoints to revenue amounts. Source labels explicitly declaring
`A: %of B` or `A share of B` now also bind the intact lexical form `A/B`. This does
not calculate a ratio, infer an unspecified denominator, or let component amounts
support ratio endpoints. Tests cover both financial and nonfinancial labels.

Validation uses the real gateway with scripted offline responses, repeated and
mixed errors, independent rejections, evidence guards, source immutability, and
existing capacity tests. A local `.692` replay supplied its actual rejected raw
response, then an explicitly simulated shorter response and simulated independent
review. It completed integration in three offline calls, preserving the original
file. The actual ratio takeaway also passed endpoint validation. This demonstrates
the recovery path, not a live model run or full-document completion. No private
export contents are committed as fixtures.
