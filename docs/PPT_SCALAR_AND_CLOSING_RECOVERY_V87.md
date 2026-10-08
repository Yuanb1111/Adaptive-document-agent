# Scalar insight and closing recovery (v87)

A scalar tool result does not identify its output unit. The previous deterministic
insight fallback could describe a growth result as the input metric's reported
level. It now presents bounded, qualified raw input values with their retained
periods and source units instead of guessing the scalar's meaning. The original
calculation and its provenance remain available in analysis results.

New and cached optional closing statements receive independent numeric, direction
and source-scope checks on their own linked observations. Unsupported closing copy
is withheld and recorded in the audit. Other conclusions remain visible. Raw
insights, extracted values and calculation results are preserved; analytical pages
still pass the normal strict export gates.

Topic recovery withdraws conflicting measure endpoints together with ambiguous
period claims. Both revert to the same model-selected question, without assigning
new meanings or inferring missing periods. The candidate must still remove errors
without introducing new ones and pass full plan validation. This prevents one
unrelated endpoint error from rejecting an otherwise safe recovery transaction.

Pipeline v87 and analysis v43 invalidate affected analysis caches. Extraction v3
is unchanged; the PPT build key is v12. Saved analysis can be replayed through the
export recovery without any model or network request. A running Streamlit instance
with source reload disabled requires a restart to load these changes.

Regression cases cover scalar growth versus reported levels in operational,
survey and financial measures, explicit validated rates, cached closing siblings,
raw-data preservation, and simultaneous metric/period scope recovery. The existing
calculated-conclusion fixture now binds its rate to actual source inputs rather
than accepting an unrelated percentage without calculation provenance.

Local replay of the user's analysis63 retained all 1,470 observations and the
original insights/calculations, recovered six selected themes, and produced a
25-slide deck. Every slide was rendered in local PowerPoint, the strict visual
gate passed without repair, and Contents occupied one page. Ambiguously bound
takeaways remain review items in the audit rather than published assertions.

Final regression verification: 2,916 Python tests passed and 8 optional tests were
skipped. Windows transport probes initialize TLS and the cached tokenizer before
scrubbing their environment; HTTP remains intercepted. Dependency warnings about
pytest rewriting and Windows event-loop cleanup remain non-failing diagnostics.
