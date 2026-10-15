"""Workflow identities for timing, independent of batch/status display copy."""

_GROUPS = {
    'startup': ('Waiting to start', 'Starting analysis'),
    'pdf_reading': ('Reading PDF', 'Reading PDF page map'),
    'requirements': ('Interpreting analysis and presentation requirements',),
    'discovery': (
        'Understanding document',
        'Mapping the large document and selecting relevant sections',
        'Checking unselected source sections within the supplementary budget',
        'Merging selected sections into the global document profile',
        'Selecting evidence-bearing page ranges',
        'Analysis scope ready for confirmation',
    ),
    'extraction': (
        'Extracting tables from selected sections', 'Extracting structured observations',
        'Normalizing financial data layer', 'Building document model',
        'Evidence unexpectedly sparse; triggering multi-strategy extraction recovery pass',
    ),
    'analysis_selection': (
        'Generating analysis candidates', 'Selecting useful analyses',
        'Reusing extracted evidence for selected analyses',
    ),
    'calculation': (
        'Running deterministic calculations', 'Checking consistency and validating results',
        'Recalculating and validating recovered evidence',
    ),
    'report_planning': (
        'Generating insights and dynamic report',
        'Planning report outline and selecting presentation questions',
        'Planning report outline', 'Selecting presentation questions before chart generation',
    ),
    'chart_generation': ('Generating charts from selected presentation questions',),
    'presentation_planning': (
        'Planning presentation narrative', 'Writing the evidence-bound executive briefing',
        'Retrying introduction with retained extraction and calculations',
        'Refining analytical priorities using actual physical slide costs',
        'Regenerating and independently checking the briefing against the final budgeted topics',
    ),
    'finalization': (
        'Complete', 'Checking requested report customizations',
        'Preparing complete display text for translation', 'Verifying requested report coverage',
    ),
    'export_evidence': ('Checking PowerPoint evidence',),
    'export_build': ('Building PowerPoint',),
    'export_layout': ('Rendering and checking PowerPoint layout',),
}
_IDENTITIES = {message: identity for identity, messages in _GROUPS.items() for message in messages}
_BATCH_PREFIXES = {
    'Understanding selected pages ': 'discovery',
    'Understood selected pages ': 'discovery',
    'Understanding selected sections with ': 'discovery',
    'Scoring analysis candidates (': 'analysis_selection',
    'Translating and reviewing display text (': 'finalization',
}


def stage_identity(message: str, current: str) -> str:
    """Only known workflow boundaries change the clock; other text is detail.

    Messages contain no document semantics here: these are application workflow
    events. New callers may pass an explicit identity to ProcessingProgress.update.
    """
    if message in _IDENTITIES:
        return _IDENTITIES[message]
    return next((identity for prefix, identity in _BATCH_PREFIXES.items()
                 if message.startswith(prefix)), current)
