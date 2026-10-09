"""Show interpreted instructions and observed completion without exposing schema internals."""


def render(st, result):
    requirements = result.profile.report_requirements
    if not requirements:
        return
    from .overview import _literal
    st.subheader('Your report requirements')
    descriptions = {r.id: r.description for r in requirements.items}
    labels = {'planned': 'Awaiting export verification', 'satisfied': 'Completed for the checked scope',
              'partial': 'Partially completed / needs review', 'not_met': 'Not completed',
              'unsupported': 'Not supported', 'ambiguous': 'Needs clarification'}
    for check in result.customization_report:
        st.markdown('**' + _literal(descriptions.get(check.requirement_id, 'Report requirements')) + '**')
        st.caption(labels[check.status])
        st.text(check.message)
        if check.slide_numbers:
            st.caption('PPT pages: ' + ', '.join(map(str, check.slide_numbers)))
    if not result.customization_report:
        for item in requirements.items:
            st.text(item.description)
            st.caption('Fulfillment has not been verified.')
