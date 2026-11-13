"""Complete three-page checks fit a bounded input without silent prefixes."""
import json

from adaptive_document_agent.agent import source_coverage as module
from adaptive_document_agent.models.coverage import SourceCheck,SourceCoverage
from tests.test_source_coverage import sample,gateway


def test_navigation_receives_exact_full_page_sizes_and_the_reading_limit():
    document,ranges=sample()
    llm=gateway([dict(targets=[],rationale='No bounded target selected.')])
    module.check_source_scope(document,ranges,llm)
    payload=json.loads(llm.client.calls[0][-1]['content'].split('\n',1)[1].rsplit('\n',1)[0])
    assert payload['maximum_source_text_characters']==module.MAX_EXCERPT_CHARS
    assert payload['source_page_text_sizes']==[[p.page_number,len(p.text)] for p in document.pages]
    assert len(payload['page_index'])==document.page_count


def test_complete_three_page_target_above_the_old_limit_is_sent_whole(monkeypatch):
    from adaptive_document_agent.agent import source_check_repair
    document,_=sample()
    for page in document.pages[4:7]:page.text+='\n'+'Complete source data. '*350
    source={p.page_number:p.text for p in document.pages[4:7]}
    assert 18000<sum(map(len,source.values()))<=module.MAX_EXCERPT_CHARS
    seen=[]
    def read(gateway,messages,schema,actual,check,ledger,**kwargs):
        seen.append(actual)
        return schema(found=True,finding='The bounded source contains the requested condition.',
            quotes=[dict(page=5,text='Literal source condition at 5.')])
    monkeypatch.setattr(source_check_repair,'source_check_request',read)
    check=SourceCheck(section_id='conditions',pages=[5,6,7],reason='Read complete condition.',decision_impact='Qualifies scope.')
    ledger=SourceCoverage()
    assert module.read_source_check(document,None,check,ledger)
    assert seen==[source] and check.status=='checked_found'
    assert not ledger.full_source_review_complete and ledger.max_calls==7


def test_target_above_the_new_limit_still_fails_without_a_partial_read(monkeypatch):
    from adaptive_document_agent.agent import source_check_repair
    document,_=sample();document.pages[4].text='x'*(module.MAX_EXCERPT_CHARS+1)
    def forbidden(*args,**kwargs):raise AssertionError('No partial excerpt may be sent')
    monkeypatch.setattr(source_check_repair,'source_check_request',forbidden)
    check=SourceCheck(section_id='conditions',pages=[5],reason='Read full source.',decision_impact='Qualifies scope.')
    ledger=SourceCoverage()
    assert not module.read_source_check(document,None,check,ledger)
    assert check.status=='incomplete' and not check.evidence_quotes and not ledger.calls_used
