"""Only explicit, same-row coordinated ranges gain repeated metric subjects."""
import pytest

from adaptive_document_agent.agent.explicit_direction_copy import expand_coordinated_directions


def rows(periods, *, metric='Operating balance'):
    return [dict(id=f'row-{i}', metric_original=metric, period=period,
        value=value, raw_value=str(value), confidence=.99, table_id='table-1', row_id=4,
        column_id=i, period_type='balance_sheet_date', period_basis='point_in_time', unit='RMB',
        unit_scale=1.0,
        raw_unit='RMB thousand', unit_family='currency', currency='RMB',
        dimensions={}, category_dimensions={}, audited_status=status)
        for i,(period,value,status) in enumerate(periods)]


def test_expands_continuous_exact_ranges_to_standalone_metric_subject_sentences():
    primary=rows([
        ('2021-12-31',10,'unknown'),('2022-12-31',20,'unknown'),
        ('2023-12-31',15,'unknown'),('2024-06-30',12,'unknown'),
        ('2024-10-31',13,'unaudited')])
    original=('Operating balance rose from 2021-12-31 to 2022-12-31, '
        'fell from 2022-12-31 to 2023-12-31, fell from 2023-12-31 to 2024-06-30, '
        'and rose from 2024-06-30 to 2024-10-31 (unaudited).')
    expected=('Operating balance rose from 2021-12-31 to 2022-12-31. '
        'Operating balance fell from 2022-12-31 to 2023-12-31. '
        'Operating balance fell from 2023-12-31 to 2024-06-30. '
        'Operating balance rose from 2024-06-30 to 2024-10-31 (unaudited).')
    assert expand_coordinated_directions(original,primary)==expected


def test_unsorted_rows_and_other_sentences_are_preserved():
    primary=rows([('FY2023',15,'unknown'),('FY2021',10,'unknown'),('FY2022',20,'unknown')])
    original=('Levels are shown above. Operating balance rose from FY2021 to FY2022, '
              'and fell from FY2022 to FY2023. The source discusses funding.')
    expected=('Levels are shown above. Operating balance rose from FY2021 to FY2022. '
              'Operating balance fell from FY2022 to FY2023. The source discusses funding.')
    assert expand_coordinated_directions(original,primary)==expected


def test_expands_inherited_widened_verb_across_explicit_same_basis_pairs():
    primary=rows([
        ('FY2021',-41756,'audited'),('FY2022',-52477,'audited'),
        ('FY2023',-103281,'audited'),('6M2023',-51687,'unaudited'),
        ('6M2024',-59883,'reviewed')], metric='Loss for the year/period')
    annual, interim = primary[:3], primary[3:]
    for row in annual:
        row.update(period_type='fiscal_year', period_basis='FY', dimensions={'period_basis': 'FY'})
    for row in interim:
        row.update(period_type='interim_flow', period_basis='6M', dimensions={'period_basis': '6M'})
    original=('Loss for the year/period widened from FY2021 to FY2022, '
        'from FY2022 to FY2023, and from 6M2023 to 6M2024.')
    expected=('Loss for the year/period widened from FY2021 to FY2022. '
        'Loss for the year/period widened from FY2022 to FY2023. '
        'Loss for the year/period widened from 6M2023 to 6M2024.')
    assert expand_coordinated_directions(original,annual)==original
    assert expand_coordinated_directions(original,annual,interim)==expected


def test_does_not_expand_range_pair_crossing_annual_and_interim_periods():
    primary=rows([
        ('FY2021',-41756,'audited'),('FY2022',-52477,'audited'),
        ('6M2023',-51687,'unaudited'),('6M2024',-59883,'reviewed')],
        metric='Loss for the year/period')
    original=('Loss for the year/period widened from FY2022 to 6M2023, '
        'and from 6M2023 to 6M2024.')
    assert expand_coordinated_directions(original,primary)==original


@pytest.mark.parametrize('mutation',[
    'prefix_subject','other_subject','unknown_period','relative_endpoint',
    'multiple_metrics','multiple_rows','multiple_tables','different_dimensions',
    'different_basis','different_currency','different_scale','quoted_copy','single_range',
])
def test_ambiguous_or_unsupported_copy_is_returned_unchanged(mutation):
    primary=rows([('FY2021',10,'unknown'),('FY2022',20,'unknown'),('FY2023',15,'unknown')])
    original='Operating balance rose from FY2021 to FY2022, and fell from FY2022 to FY2023.'
    if mutation=='prefix_subject':
        original=original.replace('Operating balance','The operating balance',1)
    elif mutation=='other_subject':
        original=original.replace('and fell','and cash fell')
    elif mutation=='unknown_period':
        original=original.replace('FY2023','FY2024')
    elif mutation=='relative_endpoint':
        original=original.replace('from FY2022 to FY2023','through the latest period')
    elif mutation=='multiple_metrics':
        primary[1]['metric_original']='Cash balance'
    elif mutation=='multiple_rows':
        primary[1]['row_id']=5
    elif mutation=='multiple_tables':
        primary[1]['table_id']='table-2'
    elif mutation=='different_dimensions':
        primary[1]['category_dimensions']={'category':'North'}
    elif mutation=='different_basis':
        primary[1]['period_type']='fiscal_year'
    elif mutation=='different_currency':
        primary[1]['currency']='USD'
    elif mutation=='different_scale':
        primary[1]['unit_scale']=1000.0
    elif mutation=='quoted_copy':
        original='“'+original+'”'
    elif mutation=='single_range':
        original='Operating balance rose from FY2021 to FY2022.'
    assert expand_coordinated_directions(original,primary)==original


def test_inserted_subject_does_not_make_wrong_direction_valid():
    from adaptive_document_agent.models import Observation,PresentationSlide
    from adaptive_document_agent.validation.claim_validator import ClaimValidator

    primary=rows([('FY2021',10,'unknown'),('FY2022',20,'unknown'),('FY2023',15,'unknown')])
    text='Operating balance rose from FY2021 to FY2022, and rose from FY2022 to FY2023.'
    expanded=expand_coordinated_directions(text,primary)
    observations=[Observation(id=row['id'],metric_original=row['metric_original'],
        period=row['period'],value=row['value'],raw_value=row['raw_value'],confidence=.99,
        table_id=row['table_id'],row_id=row['row_id'],period_type=row['period_type'],
        period_basis=row['period_basis'],unit=row['unit'],raw_unit=row['raw_unit'],
        currency=row['currency'],unit_family=row['unit_family']) for row in primary]
    slide=PresentationSlide(id='analysis',slide_type='analysis',title='Operating balance',
        message=expanded,observation_ids=[row['id'] for row in primary])
    issues=ClaimValidator().validate_slide(slide,observations)
    assert any(issue.code=='directional_contradiction' for issue in issues)
