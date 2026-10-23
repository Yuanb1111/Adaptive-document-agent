"""Existing amount-binding limits, based only on retained observation types."""


def audit_binding_ineligibility(observation):
    """Explain the existing predicate without reclassifying source observations."""
    restrictions = []
    if observation['fact_type'] != 'reported_fact':
        restrictions.append(dict(field='fact_type', retained_value=observation['fact_type'],
                                 reason='This operation binds only reported facts.'))
    if observation['ifrs_status'] in {'NON_IFRS', 'ADJUSTED'}:
        restrictions.append(dict(field='ifrs_status', retained_value=observation['ifrs_status'],
                                 reason='Adjusted and non-IFRS measures are outside amount binding.'))
    if observation['unit_family'] == 'percentage':
        restrictions.append(dict(field='unit_family', retained_value=observation['unit_family'],
                                 reason='Percentage measures are outside amount binding.'))
    if observation['unit'] in {'percent', 'ratio', 'multiple'}:
        restrictions.append(dict(field='unit', retained_value=observation['unit'],
                                 reason='Percentage, ratio and multiple measures are outside amount binding.'))
    return restrictions
