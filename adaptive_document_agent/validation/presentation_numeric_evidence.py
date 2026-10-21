"""Source-typed numeric fields shared by slide and theme validation."""
import re


def observation_numeric_fields(item, *, include_context=False):
    """Preserve source numbers; add '%' only for explicitly typed percentages.

    A bare amount, ratio or unrelated observation never licenses a percentage.
    Fields stay separate so a grouped value cannot swallow an adjacent year.
    """
    values = [item.raw_value, item.value, item.period]
    if include_context:
        values.extend((item.entity, item.dimensions))
    fields = [str(value) for value in values if value is not None]
    if item.unit == 'percent' or item.unit_family == 'percentage':
        if item.value is not None:
            fields.append(f'{item.value}%')
        if re.fullmatch(r'[+-]?[\d,.]+', item.raw_value.strip()):
            fields.append(item.raw_value + '%')
    return fields
