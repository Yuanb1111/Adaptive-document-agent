"""Resume source-complete semantic coverage on an existing analysis checkpoint."""
from .presentation_topic_selector import PresentationTopicSelector, series_directory
from .topic_coverage_review import review_topic_coverage, source_period_views, coverage_review_pending


def complete_topic_coverage(gateway, result):
    """Review retained facts without rerunning extraction or guessing omissions."""
    if not result.presentation_topics or not result.presentation_topics.topics:
        raise ValueError('Coverage completion requires an existing evidence-bound topic selection.')
    directory, lookup = series_directory(result)
    if not directory:
        raise ValueError('Coverage completion requires retained source series.')
    columns = list(directory[0])
    payload = dict(document_purpose=result.profile.document_purpose,
        user_focus=result.profile.analysis_focus,
        primary_analysis_ranges=result.profile.analysis_page_ranges,
        important_sections=result.profile.important_sections,
        series_columns=columns,
        reported_point_columns=['observation_id', 'period', 'raw_value', 'value', 'unit_scale',
            'period_basis', 'period_type', 'period_start', 'period_end', 'definition_basis',
            'audited_status', 'validation_status', 'source_pages'],
        all_extracted_series=[[entry.get(key) for key in columns] for entry in directory],
        ratio_definitions=[dict(series_id=row['id'], definitions=row['ratio_definitions'])
                           for row in directory if row['ratio_definitions']],
        source_row_qualifications=[dict(series_id=row['id'], notes=row['source_qualifications'])
                                  for row in directory if row['source_qualifications']],
        same_source_row_period_views=source_period_views(lookup))
    primary = {p for start, end in result.profile.analysis_page_ranges for p in range(start, end + 1)}
    from .topic_evidence_review import review_topic_evidence
    selected = review_topic_evidence(result.presentation_topics, lookup, result, gateway,
        PresentationTopicSelector._validate, primary_pages=primary)
    revised = review_topic_coverage(selected, result, lookup, primary,
                                   payload, gateway, PresentationTopicSelector._validate)
    checked = review_topic_evidence(revised, lookup, result, gateway,
        PresentationTopicSelector._validate, primary_pages=primary, allow_correction=False)
    if checked != revised:
        raise ValueError('Coverage synthesis introduced unsupported topic meaning; source coverage needs review.')
    result.presentation_topics = checked
    if coverage_review_pending(result):
        raise ValueError('Source coverage remains unresolved; inspect the retained review audit.')
    return result.presentation_topics
