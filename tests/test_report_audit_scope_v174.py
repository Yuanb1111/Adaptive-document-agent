"""Assurance is reviewed per exact amount; raw inputs and ratio uncertainty survive."""
from copy import deepcopy

import pytest

from adaptive_document_agent.agent.report_audit_scope import (
    AuditScopeDraft, AuditScopeReview, review_report_audit_scope, reviewed_audit_bindings,
    needs_report_audit_scope, require_report_audit_scope,
)
from adaptive_document_agent.models import Observation, PresentationPlan, PresentationTheme, PresentationSlide
from adaptive_document_agent.models.coverage import SourceCheck, SourceCoverage
from adaptive_document_agent.models.evidence import SourceEvidence
from adaptive_document_agent.services.report_audit_scope import bind_brief_audit_inventory, report_audit_scope_notes
from adaptive_document_agent.services.presentation_context_notes import slide_context_notes
from tests.test_executive_brief import result_for


def fixture():
    target = 'Example Group consolidated results for 6M2025. Revenue 120,462. Margin 20.0%. Amounts in RMB thousands.'
    scope = ('Example Group financial statements for the Relevant Periods were audited. '
             'The Relevant Periods include the six months ended 30 June 2025. The statements are on pages 5 to 7.')
    grid = 'Example Group consolidated results. Six months ended 30 June 2025. RMB’000. Revenue 120,462.\n5\n'
    result = result_for([target, 'Other source information.', 'Other evidence.', scope, grid, 'Notes.', 'Notes.'])
    common = dict(period='6M2025', entity='Example Group', confidence=1, table_id='amounts', row_id=0,
                  evidence=[SourceEvidence(page=1, text='120,462', table_id='amounts', row_label='Revenue',
                                           extraction_method='digital_table', confidence=1)])
    amount = Observation(id='amount', metric_original='Revenue', value=120462000, raw_value='120,462',
                         unit='currency', raw_unit='RMB thousands', unit_scale=1000, currency='RMB',
                         unit_family='currency', column_id=1, **common)
    ratio = Observation(id='ratio', metric_original='Margin', value=20, raw_value='20.0%', unit='percent',
                        raw_unit='%', unit_scale=1, unit_family='percentage', column_id=2, **common)
    result.observations = [amount, ratio]
    theme = PresentationTheme(id='theme', title='Results', question='What changed?', rationale='Material results',
                              observation_ids=['amount', 'ratio'], caveats=['6M2025 audit status is unknown.'])
    slide = PresentationSlide(id='slide', title='Results', slide_type='analysis', theme_id='theme',
                              observation_ids=['amount', 'ratio'])
    result.presentation_plan = PresentationPlan(title='Results', themes=[theme], slides=[slide])
    result.profile.source_coverage = SourceCoverage(checks=[SourceCheck(section_id='assurance', pages=[3, 4, 5],
        reason='Check assurance', decision_impact='Qualifies results', status='checked_found', finding=scope)])
    binding = dict(observation_id='amount', status='audited', period='6M2025', entity='Example Group',
        source_entity='Example Group', source_metric='Revenue', source_raw_value='120,462',
        source_unit='RMB’000', source_unit_scale=1000, source_currency='RMB',
        target_quote=dict(page=1, text=target), value_quote=dict(page=5, text='Revenue 120,462.'),
        header_quote=dict(page=5, text='Six months ended 30 June 2025.'),
        unit_quote=dict(page=5, text='RMB’000. Revenue 120,462.'),
        scope_evidence=[dict(page=4, text=scope)], reason='Same entity, six-month period and exact amount.')
    return result, binding


def covered_source(binding):
    """The fixture's explicit scope is pages 5–7, with page 5's printed marker."""
    return dict(covered_value_quote=deepcopy(binding['value_quote']),
        covered_header_quote=deepcopy(binding['header_quote']),
        covered_unit_quote=deepcopy(binding['unit_quote']),
        page_coverage=[dict(page=5, basis='explicit_page_range',
            scope_quote=deepcopy(binding['scope_evidence'][0]), range_start_label='5',
            range_end_label='7', covered_page_label='5', page_label_quote=dict(page=5, text='5'))])


class Gateway:
    def __init__(self, binding, *, accepted=True, unresolved_accepted=True):
        self.binding = deepcopy(binding)
        self.accepted = accepted
        self.unresolved_accepted = unresolved_accepted
        self.calls = []

    def generate_structured(self, messages, schema, **kwargs):
        self.calls.append((schema, messages, kwargs))
        if schema is AuditScopeDraft:
            return schema(bindings=[self.binding], unresolved_observation_ids=['ratio'],
                          unresolved_reason='The percentage itself has no assurance evidence.')
        assert schema is AuditScopeReview
        return schema(verdicts=[dict(observation_id='amount', accepted=self.accepted,
                                    covered_source=covered_source(self.binding) if self.accepted else None,
                                    reason='The precise amount is supported.' if self.accepted else 'Wrong scope.')],
                      unresolved_accepted=self.unresolved_accepted,
                      unresolved_reason='The ratio is outside the amount assurance scope.')


def test_review_resolves_exact_amount_only_and_preserves_all_raw_data():
    result, binding = fixture()
    original = deepcopy((result.observations, result.document, result.analysis_results))
    gateway = Gateway(binding)
    review_report_audit_scope(gateway, result)
    assert set(reviewed_audit_bindings(result)) == {'amount'}
    assert (result.observations, result.document, result.analysis_results) == original
    assert result.observations[0].audited_status == 'unknown'
    assert len(gateway.calls) == 2
    assert all(call[2]['stage'] == 'report' and not call[2]['allow_repair'] for call in gateway.calls)
    review_report_audit_scope(gateway, result)
    assert len(gateway.calls) == 2
    notes = report_audit_scope_notes(result, result.observations)
    assert any('Revenue: audited' in note for note in notes)
    assert any('Margin: audit status is not established' in note for note in notes)


@pytest.mark.parametrize('field,value', [('source_raw_value', '120,463'), ('source_unit_scale', 1),
    ('source_currency', 'USD'), ('period', '6M2024'), ('source_entity', 'Other Group')])
def test_mismatched_value_currency_period_or_entity_never_reaches_semantic_approval(field, value):
    result, binding = fixture()
    binding[field] = value
    gateway = Gateway(binding)
    with pytest.raises(ValueError):
        review_report_audit_scope(gateway, result)
    assert not reviewed_audit_bindings(result)
    assert all(call[0] is AuditScopeDraft for call in gateway.calls)
    assert result.validation_warnings[-1].code == 'report_audit_scope_unresolved'


def test_literal_row_cannot_overrule_rejected_independent_assurance_review():
    result, binding = fixture()
    gateway = Gateway(binding, accepted=False)
    with pytest.raises(ValueError, match='Wrong scope'):
        review_report_audit_scope(gateway, result)
    assert len(gateway.calls) == 4
    assert not reviewed_audit_bindings(result)


@pytest.mark.parametrize('mutation', ['source', 'value'])
def test_review_expires_when_exact_source_or_observation_changes(mutation):
    result, binding = fixture()
    review_report_audit_scope(Gateway(binding), result)
    if mutation == 'source':
        result.document.pages[3].text += ' The latest period is excluded.'
    else:
        result.observations[0].value += 1000
    assert not reviewed_audit_bindings(result)


def test_brief_grid_status_changes_only_for_its_bound_row_and_amount_column():
    result, binding = fixture()
    review_report_audit_scope(Gateway(binding), result)
    inventory = [dict(page=1, table_id='amounts', row_labels=['Revenue', 'Other amount'],
                      columns=[dict(column=1, period='6M2025', status='unknown'),
                               dict(column=2, period='6M2025', status='unknown')])]
    resolved = bind_brief_audit_inventory(inventory, result)
    assert [column['status'] for column in resolved[0]['columns']] == ['audited', 'unknown']
    assert [column['status'] for column in resolved[1]['columns']] == ['unknown', 'unknown']
    assert inventory[0]['columns'][0]['status'] == 'unknown'


def test_slide_replaces_obsolete_blanket_status_but_retains_unrelated_limitations():
    result, binding = fixture()
    result.presentation_plan.themes[0].caveats.append('Figures exclude acquisitions.')
    review_report_audit_scope(Gateway(binding), result)
    slide = result.presentation_plan.slides[0]
    notes = slide_context_notes(result, slide, [], {o.id: o for o in result.observations})
    assert '6M2025 audit status is unknown.' not in notes
    assert 'Figures exclude acquisitions.' in notes
    assert any('Revenue: audited' in note for note in notes)
    assert any('Margin: audit status is not established' in note for note in notes)


def test_no_qualifier_or_source_checks_requires_no_new_model_call():
    result, binding = fixture()
    result.presentation_plan.themes[0].caveats = []
    gateway = Gateway(binding)
    review_report_audit_scope(gateway, result)
    assert not gateway.calls


def test_latest_unresolved_event_blocks_old_approval_and_forces_fresh_review():
    from adaptive_document_agent.models import ValidationIssue
    result, binding = fixture()
    gateway = Gateway(binding)
    review_report_audit_scope(gateway, result)
    result.validation_warnings.append(ValidationIssue(code='report_audit_scope_unresolved',
        severity='warning', stage='report', message='A later attempt failed.'))
    assert not reviewed_audit_bindings(result)
    with pytest.raises(ValueError, match='unfinished or stale'):
        require_report_audit_scope(result)
    review_report_audit_scope(gateway, result)
    assert len(gateway.calls) == 4
    require_report_audit_scope(result)


def test_final_gate_accepts_reduced_scope_but_rejects_new_unreviewed_measure():
    result, binding = fixture()
    assert needs_report_audit_scope(result)
    with pytest.raises(ValueError):
        require_report_audit_scope(result)
    review_report_audit_scope(Gateway(binding), result)
    require_report_audit_scope(result)
    extra = result.observations[0].model_copy(deep=True, update=dict(id='new', row_id=1))
    result.observations.append(extra)
    result.presentation_plan.themes[0].observation_ids.append('new')
    with pytest.raises(ValueError):
        require_report_audit_scope(result)
    result.presentation_plan.themes[0].observation_ids = ['amount']
    require_report_audit_scope(result)
    result.presentation_plan.themes[0].caveats = []
    assert not needs_report_audit_scope(result)
    require_report_audit_scope(result)
