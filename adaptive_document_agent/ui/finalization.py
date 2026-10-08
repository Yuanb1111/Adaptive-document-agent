"""Review a bounded topic revision before applying it to the downloadable draft."""
from adaptive_document_agent.services import finalization as editing


def render(st,result,settings,scope_key):
    plan=getattr(result,'presentation_plan',None)
    if plan is None or not plan.themes:return result
    key='finalization_'+scope_key
    state=st.session_state.setdefault(key,{})
    original=editing.digest(dict(facts=editing.fact_hash(result),plan=plan.model_dump(mode='json')))
    if state.get('source_hash')!=original:
        state.clear();state['source_hash']=original
    current=state.get('applied',result)
    with st.expander('Edit and finalize selected topics',expanded=False):
        st.caption('Lock topic content, change its order, or rewrite one topic using its existing evidence. Review the changes before applying them. Original analysis stays available.')
        lookup={t.id:t.title for t in current.presentation_plan.themes};ids=list(lookup)
        selected=st.selectbox('Topic',ids,format_func=lambda i:lookup[i],key=key+'_target')
        locks=st.multiselect('Lock topic content',ids,default=list((current.finalization or {}).get('locked_hashes',{})),format_func=lambda i:lookup[i],key=key+'_locks')
        if st.button('Save content locks',key=key+'_save_locks'):
            try:state['applied']=editing.set_locks(current,locks);state.pop('pending',None);st.rerun()
            except ValueError as exc:st.error(str(exc))
        position=ids.index(selected)
        left,right=st.columns(2)
        up=left.button('Move topic up',disabled=position==0,key=key+'_up')
        down=right.button('Move topic down',disabled=position==len(ids)-1,key=key+'_down')
        if up or down:
            state.pop('pending',None)
            order=ids[:];other=position-1 if up else position+1;order[position],order[other]=order[other],order[position]
            try:state['pending']=editing.reorder(current,order)
            except ValueError as exc:st.error(str(exc))
        instruction=st.text_area('What should change in this topic?',key=key+'_instruction',placeholder='Keep the financial facts; shorten the description and emphasize the causes supported by the source.')
        length=st.selectbox('Topic length',['Concise','Balanced','Detailed'],index=1,key=key+'_length')
        st.caption('Rewriting makes one model request with the selected topic evidence. Changing order or locks makes no model requests.')
        if st.button('Prepare selected topic revision',key=key+'_rewrite',disabled=selected in locks or not instruction.strip()):
            from adaptive_document_agent.services.llm import LLMGateway
            from adaptive_document_agent.services.llm.routing import create_llm_client
            state.pop('pending',None)
            gateway=None
            try:
                gateway=LLMGateway(create_llm_client(settings),settings,cache_enabled=False)
                with st.spinner('Revising the selected topic and checking evidence…'):
                    state['pending']=editing.revise_topic(current,selected,instruction,length.lower(),gateway)
            except Exception as exc:
                if gateway:current.llm_usage.extend(gateway.usage)
                st.error('Revision was not applied: '+str(exc))
        pending=state.get('pending')
        if pending:
            change=pending.finalization['revisions'][-1]
            st.markdown('**Review changes**')
            if change['operation']=='reorder':
                st.write(' → '.join(lookup[i] for i in change['changes']['after']))
            else:
                for item in change['changes']:st.code(item['diff'],language='diff')
            st.write('Supporting evidence:',change['evidence'])
            if st.button('Apply reviewed draft',key=key+'_apply'):
                # Revalidate current locks; a prepared proposal cannot bypass
                # a lock or another revision applied after its creation.
                try:
                    if (pending.finalization or {}).get('locked_hashes',{})!=(current.finalization or {}).get('locked_hashes',{}):
                        raise ValueError('Content locks changed; prepare the revision again.')
                    editing.assert_stable(pending);state['applied']=pending;state.pop('pending');st.rerun()
                except ValueError as exc:st.error(str(exc))
            if st.button('Discard proposed changes',key=key+'_discard'):state.pop('pending');st.rerun()
        if current.finalization:
            st.caption(f"Applied revisions: {len(current.finalization['revisions'])}. Facts, charts, briefing and locked topic content are checked for stability.")
            if st.button('Restore original presentation',key=key+'_restore'):
                state.pop('applied',None);state.pop('pending',None);st.session_state.pop(key+'_locks',None);st.rerun()
    return current
