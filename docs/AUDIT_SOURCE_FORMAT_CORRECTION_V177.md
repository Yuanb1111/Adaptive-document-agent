# Audit source selection format correction (v177)

The `.634` export ran v176 and completed introduction and presentation coverage
review. It stopped at `report_audit_scope` because `AuditSourceDiscovery` returned
four ranges with per-range reasons but omitted its required top-level `rationale`.
The response ended normally (`stop`, 780 output tokens). The gateway rejected its
schema, while source discovery's correction loop only handled valid-schema
selections with invalid page ranges. Capacity recovery intentionally did not retry
this complete response.

Source discovery now handles complete structured-output failures within the same
single correction allowance as source-selection validation errors. It retains the
original response and precise schema diagnostics in the audit, sends them as
untrusted data alongside the unchanged complete navigation/source context, and
asks the model for a complete corrected response. Both the original prompt and
the correction explicitly require the overall rationale and per-range reasons.
Python does not fill missing content or approve assurance.

The corrected response must pass the original strict schema, section/page bounds,
target-ID checks, full-page availability and evidence budget. A second format or
selection error fails with a durable reporting checkpoint. Proven truncation keeps
its existing bounded capacity retry; exhausted partial output is never repaired.
Transport, privacy, cancellation and configuration errors propagate without a
content correction or provider fallback.

Regression tests exercise the real gateway with scripted offline responses,
including missing fields, malformed JSON, repeated/mixed failures, source
preservation and capacity/error boundaries. An additional local replay used the
actual `.634` rejected response and context, followed by an explicitly simulated
response supplying a rationale: two offline calls completed source discovery and
retained the raw failure unchanged. This is not a live model rerun or completion
of the full analysis. No exported document content is committed as a fixture.
