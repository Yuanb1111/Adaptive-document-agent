"""All evidence, arithmetic and independent direction gates for a completed partition."""


def validate_meaning_response(gateway, response, *, brief, pending, messages, catalogs, result=None, cancelled=None):
    errors = {}
    from .brief_review_bindings import correct_review_bindings
    response, binding_errors = correct_review_bindings(gateway, response, brief=brief,
        pending=pending, messages=messages, result=result, cancelled=cancelled)
    from .brief_meaning_evidence import review_evidence_errors
    errors.update(review_evidence_errors(response, brief=brief, pending=pending,
        catalogs=catalogs, result=result, binding_errors=binding_errors))
    # A single source reviewer can silently map "narrowed" to increase to
    # agree with the endpoints. Read audience predicates in a separate call
    # without that review, its directions, or any source values. Only a
    # comparison that survives BOTH semantic bindings can be memoized.
    from .brief_claim_direction import review_claim_directions
    correction_eligible = set()
    direction_failures = review_claim_directions(gateway, brief=brief,
        verdicts=[row for row in response.items if row.index not in errors],
        result=result, cancelled=cancelled, correction_eligible=correction_eligible)
    if correction_eligible:
        from .brief_direction_repair import correct_direction_bindings

        def revalidate(corrected):
            # No recursive correction or relaxed gate: a proposed reviewer
            # repair starts again at the original source/arithmetic checks.
            failures = review_evidence_errors(corrected, brief=brief, pending=pending,
                catalogs=catalogs, result=result)
            failures.update(review_claim_directions(gateway, brief=brief,
                verdicts=[row for row in corrected.items if row.index not in failures],
                result=result, cancelled=cancelled))
            return failures

        corrected_failures = correct_direction_bindings(gateway, response,
            messages=messages, direction_failures={index: direction_failures[index]
                for index in correction_eligible}, revalidate=revalidate,
            result=result, cancelled=cancelled)
        direction_failures = {**{index: failures for index, failures in direction_failures.items()
                                 if index not in correction_eligible}, **corrected_failures}
    errors.update(direction_failures)
    return errors
