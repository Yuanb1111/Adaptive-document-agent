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
        'Planning presentation narrative',
        'Retrying introduction with retained extraction and calculations',
    ),
    'executive_briefing': ('Writing the evidence-bound executive briefing',),
    'report_audit_scope': (
        'Reviewing source audit qualifications',
        'Locating additional source pages for exact audit qualifications',
    ),
    'presentation_budget': (
        'Refining analytical priorities using actual physical slide costs',
        'Measuring the final briefing and complete PowerPoint budget',
    ),
    'final_briefing': (
        'Regenerating and independently checking the briefing against the final budgeted topics',
    ),
    'source_integration': ('Reviewing supplementary sources against the final conclusions',),
    'finalization': ('Complete',),
    'requirements_review': ('Checking requested report customizations', 'Verifying requested report coverage'),
    'localization': ('Preparing complete display text for translation',),
    'export_evidence': ('Checking PowerPoint evidence',),
    'export_build': ('Building PowerPoint',),
    'export_layout': ('Rendering and checking PowerPoint layout',),
}
_IDENTITIES = {message: identity for identity, messages in _GROUPS.items() for message in messages}
_BATCH_PREFIXES = {
    'Briefing review: ': 'executive_briefing',
    'Company introduction semantic review failed': 'introduction_review',
    'Company introduction content repair failed': 'introduction_content_repair',
    'Company introduction reading failed': 'introduction_reading',
    'Company introduction failed': 'introduction',
    'Budget proposal ': 'presentation_budget',
    'Understanding selected pages ': 'discovery',
    'Understood selected pages ': 'discovery',
    'Understanding selected sections with ': 'discovery',
    'Scoring analysis candidates (': 'analysis_selection',
    'Translating and reviewing display text (': 'localization',
    'Linking audit qualifications: ': 'report_audit_scope',
    'Audit qualification: ': 'report_audit_scope',
    'Audit qualification source group ': 'report_audit_scope',
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
