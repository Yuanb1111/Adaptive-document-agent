from streamlit.testing.v1 import AppTest


SCRIPT='''
import streamlit as st
from tests.test_p1_theme_planning import themed_result
from adaptive_document_agent.ui.finalization import render
from adaptive_document_agent.services.llm import LLMSettings, ProviderName
result=render(st,themed_result(),LLMSettings(provider=ProviderName.MOCK),'synthetic')
st.write('locked='+str(list((result.finalization or {}).get('locked_hashes',{}))))
'''


def test_streamlit_lock_and_restore_work_without_model_calls():
    app=AppTest.from_string(SCRIPT,default_timeout=15).run()
    assert not app.exception
    app.multiselect[0].set_value(['operations']).run()
    app.button(key='finalization_synthetic_save_locks').click().run()
    assert not app.exception
    assert app.button(key='finalization_synthetic_rewrite').disabled
    assert app.session_state['finalization_synthetic']['applied'].finalization['locked_hashes']
    app.button(key='finalization_synthetic_restore').click().run()
    assert not app.exception
    assert 'applied' not in app.session_state['finalization_synthetic']
