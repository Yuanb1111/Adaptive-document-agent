"""Complete audit rationale never substitutes for bounded literal source reading."""
from copy import deepcopy

import pytest

from adaptive_document_agent.agent.source_coverage import SourceCoverageSelection, check_source_scope
from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, MockLLMClient, ProviderName
from adaptive_document_agent.services.llm.config import PrivacyMode
from adaptive_document_agent.services.llm.exceptions import PrivacyViolationError
from tests.test_source_coverage import sample, target, gateway


@pytest.mark.parametrize('length', [602, 2000])
def test_complete_rationale_is_preserved_while_every_target_still_needs_its_source_check(length):
    document, ranges = sample()
    rationale = ('Selected source windows need a bounded check of their applicable conditions. ' * 30)[:length]
    original = dict(targets=[target(5, 5), target(7, 8)], rationale=rationale)
    canonical = SourceCoverageSelection.model_validate_json(SourceCoverageSelection.model_validate(original).model_dump_json())
    assert canonical.rationale == rationale
    client = gateway([canonical.model_dump(),
        dict(found=False, finding='No requested evidence in this synthetic window.', quotes=[]),
        dict(found=False, finding='No requested evidence in this second synthetic window.', quotes=[])])
    updated, ledger = check_source_scope(document, ranges, client)
    assert ledger.notes[0] == rationale and len(ledger.notes[0]) == length
    assert len(updated) == 3 and len(ledger.checks) == 2
    assert ledger.calls_used == ledger.max_calls == len(client.client.calls) == 3
    assert all(check.status == 'checked_not_found' for check in ledger.checks)
    assert not ledger.full_source_review_complete


@pytest.mark.parametrize('fault', ['over_limit', 'missing', 'empty'])
def test_rationale_is_required_and_strictly_bounded(fault):
    value = dict(targets=[target()], rationale='Complete source-aware selection reasoning.')
    if fault == 'over_limit': value['rationale'] = 'x' * 2001
    elif fault == 'missing': value.pop('rationale')
    else: value['rationale'] = ''
    with pytest.raises(ValueError):
        SourceCoverageSelection.model_validate(value)


@pytest.mark.parametrize('fault', ['unknown_section', 'outside_section', 'too_many_pages',
                                  'already_selected', 'duplicate', 'overlapping', 'missing_source'])
def test_long_rationale_does_not_relax_scope_duplicate_or_complete_source_guards(fault):
    document, ranges = sample()
    targets = [target()]
    if fault == 'unknown_section': targets[0]['section_id'] = 'unknown-section'
    elif fault == 'outside_section': targets[0].update(start_page=3, end_page=5)
    elif fault == 'too_many_pages': targets[0]['end_page'] = 8
    elif fault == 'already_selected': targets[0].update(section_id='core', start_page=2, end_page=3)
    elif fault == 'duplicate': targets.append(deepcopy(targets[0]))
    elif fault == 'overlapping': targets.append(target(6, 7))
    else: document.pages = [page for page in document.pages if page.page_number != 6]
    client = gateway([dict(targets=targets, rationale='A' * 602)])
    before = document.model_dump_json()
    updated, ledger = check_source_scope(document, ranges, client)
    assert updated == ranges and not ledger.full_source_review_complete
    assert document.model_dump_json() == before
    if fault in {'duplicate', 'overlapping'}:
        assert len(ledger.checks) == 1 and ledger.checks[0].status == 'failed'
        assert ledger.calls_used == 2  # Missing mock read is a failure, never an approval.
        assert any('overlapping' in note for note in ledger.notes)
    elif fault == 'missing_source':
        assert len(ledger.checks) == 1 and ledger.checks[0].status == 'incomplete'
        assert ledger.calls_used == 1
    else:
        assert not ledger.checks and ledger.calls_used == 1


def test_capacity_change_keeps_target_count_limit_and_local_only_authorization():
    with pytest.raises(ValueError):
        SourceCoverageSelection(targets=[target(), target(7, 7), target(8, 8)], rationale='A' * 602)
    with pytest.raises(PrivacyViolationError):
        LLMGateway(MockLLMClient(), LLMSettings(provider=ProviderName.DEEPSEEK,
                                               privacy_mode=PrivacyMode.LOCAL_ONLY))
