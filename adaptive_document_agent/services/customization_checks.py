"""Observable fulfillment, kept separate from immutable source and analytical facts."""

from adaptive_document_agent.models.customization import RequirementCheck


def check_requirements(result, presentation=None, *, export_verified=False):
    requirements = result.profile.report_requirements
    if not requirements:
        return
    prior = {c.requirement_id: c for c in result.customization_report}
    checks = []
    if requirements.interpretation_error:
        checks.append(RequirementCheck(requirement_id='interpretation', status='not_met',
                                      message=requirements.interpretation_error))
    if requirements.conflicts:
        checks.append(RequirementCheck(requirement_id='conflicts', status='ambiguous',
                                      message='; '.join(requirements.conflicts)))
    table_pages = {}
    if presentation is not None:
        from .requested_tables import verify_requested_tables
        table_pages = verify_requested_tables(presentation, result)
    from .requested_tables import requested_table_catalog
    catalog = requested_table_catalog(result)
    pages = {p.page_number: p for p in result.document.pages}
    for req in requirements.items:
        if req.resolution != 'resolved' or req.kind == 'unsupported':
            checks.append(RequirementCheck(requirement_id=req.id,
                status='ambiguous' if req.resolution == 'ambiguous' else 'unsupported',
                message=req.reason or 'This customization cannot be executed reliably.'))
        elif req.kind == 'section_tables':
            numbers = sorted({p for s in req.sections for p in range(s.start_page, s.end_page + 1)})
            records = [r for r in catalog if req.id in r['requirement_ids']]
            ids = [r['table'].table_id for r in records]
            unprocessed = [p for p in numbers if p not in pages or pages[p].table_extraction_status != 'processed']
            uncertain = [p for p in numbers if p in pages and pages[p].requires_ocr]
            uncertain += [r['page'].page_number for r in records
                          if r['table'].confidence < .6 or any(w !=
                              'Recovered from aligned text because no bordered table structure was detected.'
                              for w in r['table'].warnings)]
            exported = sorted({p for identifier in ids for p in table_pages.get(identifier, [])})
            status = ('not_met' if not ids else 'partial' if unprocessed or uncertain else
                      'satisfied' if export_verified and exported else 'planned')
            message = f'{len(numbers)} physical pages; {len(ids)} detected source-table fragments retained.'
            if export_verified and exported:
                message += ' Every retained source cell verified in editable PPT tables.'
            if unprocessed:
                message += ' Extraction incomplete on pages: ' + ', '.join(map(str, unprocessed)) + '.'
            if uncertain:
                message += ' Source parsing needs review on pages: ' + ', '.join(map(str, sorted(set(uncertain)))) + '.'
            message += ' Counts concern detected tables; digital extraction cannot certify that no table was undetected.'
            checks.append(RequirementCheck(requirement_id=req.id, status=status, message=message,
                source_pages=numbers, table_ids=ids, slide_numbers=exported,
                verification='source_fragment_cells' if export_verified else 'extraction_inventory'))
        elif req.kind == 'slide_limit':
            count = len(presentation.slides) if presentation is not None else None
            checks.append(RequirementCheck(requirement_id=req.id,
                status='planned' if count is None else 'satisfied' if count <= req.max_slides else 'not_met',
                message=f'Requested maximum {req.max_slides} slides. ' +
                ('Actual physical slide count is not yet available.' if count is None else f'Actual count: {count}. '
                 'Required evidence was retained rather than removed to conceal a budget conflict.')))
        elif req.kind in {'table_presentation','source_citations'}:
            errors, numbers = [], []
            if presentation is not None:
                from .customization_presentation_checks import table_presentation_errors, citation_errors
                errors, numbers = (table_presentation_errors(presentation) if req.kind=='table_presentation'
                                   else citation_errors(presentation,result))
            verified = presentation is not None and export_verified
            checks.append(RequirementCheck(requirement_id=req.id,
                status='planned' if not verified else 'not_met' if errors else 'satisfied',
                message=('Native editable purple/white source tables, readable pagination and repeated source headers.'
                         if req.kind=='table_presentation' else 'Page-level source footers on source-bound slides.')
                        + (' Export verification pending.' if not verified else ' Verified in exported PPT.' if not errors
                           else ' '+ '; '.join(errors[:8])),
                slide_numbers=numbers,verification='native_table_style_and_cells' if req.kind=='table_presentation'
                else 'native_source_page_footers'))
        else:
            check = prior.get(req.id, RequirementCheck(requirement_id=req.id, status='planned',
                                                      message='Requirement supplied to report generation; fulfillment not verified.'))
            check = check.model_copy(deep=True)
            if req.kind == 'output_language' and export_verified and presentation is not None:
                from .report_language import audience_copy, original_language
                if req.language_scope == 'source_tables':
                    if original_language(req.language):
                        ids = [r['table'].table_id for r in catalog]
                        check.status = 'satisfied' if ids and all(table_pages.get(i) for i in ids) else 'not_met'
                        check.message = 'Original source-table cells verified in exported editable tables.' if ids else 'No original source tables were exported.'
                        check.verification = 'source_fragment_cells'
                    else:
                        check.status = 'unsupported'
                        check.message = 'Source tables retain literal evidence; translated source-table cells are not supported.'
                    checks.append(check)
                    continue
                mapping = requirements.copy_translations
                text = audience_copy(presentation)
                normalized = lambda value: ' '.join(value.split())
                translated = {normalized(value) for value in mapping.values()}
                remaining = [value for value in text if normalized(value) not in translated]
                if not mapping or remaining or check.status == 'partial':
                    check.status = 'partial'
                    check.message += f' {len(remaining)} display strings remain outside the checked translation.'
                elif check.status == 'planned':
                    check.status = 'satisfied'
                if req.language_scope == 'all' and catalog and not original_language(req.language):
                    check.status = 'partial'
                    check.message += ' Original evidence tables retain their literal source language.'
                check.verification = 'rendered_display_copy; numeric_tokens_preserved'
            if req.kind in {'analysis_focus', 'content_detail'} and export_verified:
                if check.status == 'planned' and check.verification.startswith('model_semantic_review_satisfied;'):
                    check.status = 'satisfied'
                displayed = {s.get('planned_slide_id') for s in result.presentation_export_trace}
                if check.status == 'satisfied' and not set(check.slide_ids) <= displayed:
                    check.status = 'partial'
                    check.message += ' Supporting planned content lacks a complete exported-slide mapping.'
                check.slide_numbers = sorted({n for record in result.presentation_export_trace
                                              if record.get('planned_slide_id') in check.slide_ids
                                              for n in record['slide_numbers']})
                check.verification = ('model_semantic_review_and_export_scope' if check.slide_numbers
                                      else 'not_verified_in_export')
            checks.append(check)
    result.customization_report = checks


def mark_customization_export_verified(result, payload):
    if result.profile.report_requirements:
        from io import BytesIO
        from pptx import Presentation
        check_requirements(result, Presentation(BytesIO(payload)), export_verified=True)
