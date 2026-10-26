# Audit review correction budgets v194

The reported v193 diagnostic ending `.346` failed in `report_audit_scope`.
Both failing completed drafts followed the same sequence:

1. The writer returned all targets as unknown.
2. The reviewer incorrectly included unknown IDs in the binding-only verdict list.
3. A reviewer output correction returned the required empty verdict list, but
   rejected one revenue observation's unknown disposition with exact source evidence.
4. The controller raised `independent_review correction budget exhausted` before
   giving the writer any content correction. Each batch contained just one draft.

This was a controller budget defect. Reviewer format/ID repair incremented the
same `independent_review` counter that guarded substantive writer correction.
Existing tests explicitly required that shared limit and consequently missed the
valid combined sequence. The sources were available and the reviewer identified
the counterpart; the feedback never reached a second draft request.

The controller now tracks three separate, finite allowances per batch:

| Correction | Allowance | Recipient |
| --- | --- | --- |
| Binding/schema validation | One | Draft writer |
| Substantive independent rejection | One | Draft writer |
| Reviewer output format or ID ledger | One across all drafts | Reviewer |

Drafts remain capped at three. A repeated review output error is a distinct
terminal exception and cannot consume a writer correction or cause a new draft.
A substantive rejection after output repair reaches the writer with the complete
rejection, exact target contracts and unchanged full source pages. The corrected
draft must pass binding validation and a fresh independent review. No rejected
unknown is automatically converted to audited or unaudited. A reviewer finding
is still untrusted opinion to verify against source evidence, not an approval.

Schema descriptions and a concrete per-request binding count clarify that an
all-unknown draft requires `verdicts=[]`, with unknown assessment in its separate
fields. Malformed IDs are still rejected rather than silently dropped. Output
token limits, length recovery, gateway/privacy rules and evidence checks are
unchanged. Transport, privacy and cancellation failures do not consume content
corrections. No semantic failure triggers smaller transport batches.

## Recorded controller replay

```text
python scripts/replay_audit_scope.py path/to/analysis_data.json --review-correction-path
```

For both failed `.346` batches (indices 4 and 5), replaying the actual recorded
draft, invalid review and corrected rejection now reaches a new draft request:

```text
AuditScopeDraft -> AuditScopeReview -> AuditScopeReview -> AuditScopeDraft
```

The replay verifies the full rejection and unchanged source context reach that
request, then stops. It does not manufacture a corrected draft or independent
approval and makes no provider calls. This establishes the repaired control flow,
not a successful live end-to-end analysis. The private diagnostic stays outside
the repository.

Synthetic regressions also exercise the continuation through a corrected exact
amount binding and fresh covered-source approval, while retaining an unsupported
ratio as unknown. Repeated rejection, repeated review-format failure, global
output-correction limits, invalid corrected amounts and all three draft limits
remain covered. Existing completed batch approvals still require exact source
and proof revalidation before reuse; the acceptance contract is unchanged.
The pipeline becomes v194; extraction and analysis cache versions are unchanged.

Validation: 573 audit, gateway/reasoning, cache and v191/v192 layout regression
tests pass. Python syntax validation and `git diff --check` pass.
