"""A repeated locator suffix preserves its coordinate; no missing proof is inferred."""
from copy import deepcopy
import pytest
from pydantic import ValidationError

from adaptive_document_agent.agent.summary_reader import ReadFact


@pytest.mark.parametrize('field',['quote_start_line','quote_end_line'])
def test_one_repeated_suffix_keeps_all_fact_values_and_original_input(field):
    raw=dict(label='Investor caution',text='The source advises reading all risk disclosures.',
             quote_start_line=4,quote_end_line=6)
    expected=deepcopy(raw)
    raw[field+'_line']=raw.pop(field)
    before=deepcopy(raw)
    assert ReadFact.model_validate(raw).model_dump()==expected
    assert raw==before


@pytest.mark.parametrize('field',['quote_start_line','quote_end_line'])
def test_conflicting_or_invalid_coordinates_are_not_repaired(field):
    raw=dict(label='Caution',text='The source describes a qualification.',quote_start_line=4,quote_end_line=6)
    with pytest.raises(ValidationError):ReadFact.model_validate({**raw,field+'_line':99})
    raw.pop(field)
    with pytest.raises(ValidationError):ReadFact.model_validate({**raw,field+'_line':0})
    with pytest.raises(ValidationError):ReadFact.model_validate(raw)
