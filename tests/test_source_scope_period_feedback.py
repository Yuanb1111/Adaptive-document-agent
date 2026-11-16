"""Correction feedback cannot create fiscal/interim aliases for dated snapshots."""
from copy import deepcopy

from adaptive_document_agent.agent.source_context_periods import scope_period_feedback
from adaptive_document_agent.agent.compact_publication_copy import compact_publication_copy
from tests.test_compact_publication_copy import payload,gateway


def test_unknown_period_diagnostics_keep_exact_bound_labels_without_converting_them():
    periods=['2020-09-30','2021-09-30'];before=deepcopy(periods)
    hint=scope_period_feedback('FY2020 and 9M2021',periods)
    assert hint['unbound_scope_period_labels']==['9M2021','FY2020']
    assert hint['exact_bound_period_labels']==periods and not hint['semantic_approval']
    assert periods==before
    assert scope_period_feedback('FY2020 and 9M2021',['FY2020','9M2021']) is None
    assert scope_period_feedback('2020-09-30',periods) is None


def test_single_correction_names_the_real_snapshot_binding_and_keeps_source_proof():
    source=payload()
    source['pages_to_correct']['owned']['primary_observations']=[dict(period='2020-09-30')]
    proof='The programme balance as of September 30, 2020 reflected procurement-related risk.'
    item=dict(scope='FY2020',description='describes procurement-related risk',quote=dict(page=2,text=proof))
    rejected=dict(message='Reported programme levels.',companion_ids=[],context_evidence=[],source_context=[item])
    corrected={**rejected,'source_context':[{**item,'scope':'2020-09-30'}]}
    llm=gateway([rejected,corrected])
    page=compact_publication_copy(llm,'owned',source,400,lambda _: {},preserve_inputs=False)['owned']
    assert page.source_context[0].scope=='2020-09-30' and page.source_context[0].quote.text==proof
    assert len(llm.client.calls)==2
    feedback=str(llm.client.calls[1])
    assert 'unbound_scope_period_labels' in feedback and 'exact_bound_period_labels' in feedback
    assert 'FY2020' in feedback and '2020-09-30' in feedback
