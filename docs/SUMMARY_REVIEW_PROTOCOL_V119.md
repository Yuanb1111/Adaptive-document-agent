# Explicit introduction review protocol (v119)

Hosted v118 standard verification used the original 524-page PDF after GitHub
Actions #166 passed. It completed analysis in 372,802 ms but blocked PPT at the
introduction check. The downloaded diagnostic is retained privately as
`analysis_data (101).json`; no successful hosted PPT is claimed.

Summary reading passed for 142 assigned parts, including 63 substantive parts.
The source-selected outline contained nine themes. The first theme's draft
explicitly described developing, manufacturing and commercializing cobots, their
users and product scope. Its independent review accepted every part and issuer
identity, but `opening_accepted` was false without an explanation on both attempts.
Because that field had a default, the stored audit cannot distinguish an omitted
model verdict from an explicit rejection. A second theme failed schema validation
twice; the audit had discarded the raw response and underlying field errors.

Make the opening verdict and its explanation required structured fields. Missing
verdicts become protocol failures, not silent semantic decisions. Require the
reviewer to identify actual first-page business/subject copy or explain exactly
what is absent. Send its explanation into the existing bounded editorial repair.

Preserve structured failures' raw responses and validation details in the private
source audit and repair payload. This supplies specific field errors to the next
attempt without relaxing schemas, numerical evidence, independent part-meaning
review, first-page business scope, privacy, or cancellation. The retry budget is
unchanged. No source content or credentials are added to public logs.

New tests reject omitted verdict/reason fields, verify concrete schema diagnostics
reach repair, and verify a rejected opening explanation reaches the editor.
Local regression: 1,141 passed and five existing tests skipped in 117.76 seconds.
