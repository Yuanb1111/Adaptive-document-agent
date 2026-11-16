"""Equivalent change-label punctuation retains exact Python interval ownership."""
import pytest

from adaptive_document_agent.validation.calculated_change_label import labelled_change_supported


def calculation(**changes):
    return dict(kind='percentage_change',unit='percent',value=-14.915,
                metric='Program budget',periods=['2021-12-31','2024-10-31'],**changes)


@pytest.mark.parametrize('label',['Calculated change: ','Calculated percentage change: ',
    'Calculated percentage change was ','Computed cumulative change in Program budget: '])
@pytest.mark.parametrize('asof',['','As of '])
def test_label_punctuation_and_calendar_prefix_preserve_bound_change(label,asof):
    clause=label+'-14.9% from '+asof+'2021-12-31 to '+asof+'2024-10-31.'
    assert labelled_change_supported(clause,label,'-14.9',[calculation()])


@pytest.mark.parametrize('label,literal,interval',[
    ('Reported budget: ','-14.9','2021-12-31 to 2024-10-31'),
    ('Calculated percentage change: ','14.9','2021-12-31 to 2024-10-31'),
    ('Calculated percentage change: ','-14.8','2021-12-31 to 2024-10-31'),
    ('Calculated percentage change: ','-14.9','2021-12-31 to 2023-10-31'),
    ('Calculated percentage change in Other budget: ','-14.9','2021-12-31 to 2024-10-31'),
])
def test_colon_label_never_lends_rate_to_wrong_level_value_interval_or_metric(label,literal,interval):
    clause=label+literal+'% from '+interval+'.'
    assert not labelled_change_supported(clause,label,literal,[calculation()])


def test_annual_in_a_literal_metric_name_is_not_an_annualized_rate():
    calc=calculation();calc['metric']='Annual program expenditure'
    prefix='Calculated decrease in annual program expenditure was '
    clause=prefix+'14.9% from 2021-12-31 to 2024-10-31.'
    assert labelled_change_supported(clause,prefix,'14.9',[calc])
    for label in ['Calculated annual decrease was ','Annual calculated decrease was ',
                  'Calculated annualized decrease was ']:
        assert not labelled_change_supported(label+'14.9% from 2021-12-31 to 2024-10-31.',label,'14.9',[calc])


@pytest.mark.parametrize('label',[
    'Calculated Program budget percentage change was ',
    'Computed Program budget change: ',
    'Recomputed Program budget cumulative percentage change is ',
])
def test_metric_first_label_has_the_same_exact_calculation_ownership(label):
    clause=label+'-14.9% from 2021-12-31 to 2024-10-31.'
    assert labelled_change_supported(clause,label,'-14.9',[calculation()])
    for bad in [label.replace('Program budget','Other budget'),
                label.replace('Program budget','Program budget and survey score'),
                label.replace('change','annualized change')]:
        assert not labelled_change_supported(bad+'-14.9% from 2021-12-31 to 2024-10-31.',bad,'-14.9',[calculation()])
    assert not labelled_change_supported(clause,label,'14.9',[calculation()])
    assert not labelled_change_supported(clause.replace('2024-10-31','2024-06-30'),label,'-14.9',[calculation()])
