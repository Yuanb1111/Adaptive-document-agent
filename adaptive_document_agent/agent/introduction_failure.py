"""Locate a failed introduction prerequisite independently of its resume point."""
import json


def introduction_failure_details(result, failure):
    details = {'operation': 'CompanyIntroduction', 'source_pages': [],
               'kind': 'verification', 'message': str(failure)[:500]}
    stage = 'introduction'
    for issue in reversed(result.validation_warnings):
        if issue.code != 'company_introduction_summary_audit':
            continue
        try:
            audit = json.loads(issue.message)
        except (ValueError, TypeError):
            continue
        failed = next((row for row in audit.get('read_audits', []) if row.get('error')), None)
        if failed is not None:
            stage = 'introduction_reading'
            pages = failed.get('source_pages') or sorted({b['page'] for b in audit.get('source_blocks', [])
                if b.get('id') in failed.get('block_ids', [])})
            details.update(operation='SummaryReadBatch', source_pages=pages,
                           block_ids=failed.get('block_ids', []),
                           kind=failed.get('failure_kind', 'evidence'))
        elif not audit.get('plan_audits') and not audit.get('audience_selection'):
            stage = 'introduction_reading'
            details.update(operation='SummaryReadBatch', source_pages=audit.get('source_pages', []))
        else:
            stage = 'introduction_editorial'
            plans = audit.get('plan_audits', [])
            latest = next((row for row in reversed(plans) if row.get('errors')), {})
            if latest.get('revision_failed'):
                stage = 'introduction_content_repair'
                details.update(operation='SummarySynthesisRevision', kind='no_progress'
                    if 'repeated the rejected draft' in str(latest['errors']) else 'content_repair')
            elif latest.get('compact_review_attempts'):
                stage = 'introduction_review'
                details.update(operation='SummaryCoverageReview', kind='review_protocol'
                    if latest['compact_review_attempts'][-1].get('status') != 'success' else 'meaning')
            rejected = next((row.get('compact_semantic_review', {}).get('parts', [])
                for row in reversed(plans) if row.get('compact_semantic_review')), [])
            part_ids = {row['part_id'] for row in rejected if not row.get('accepted')}
            if part_ids:
                details.update(part_ids=sorted(part_ids), source_pages=sorted({part['source_page']
                    for part in audit.get('parts', []) if part.get('id') in part_ids}))
        break
    return stage, details


def introduction_failure_message(stage, details):
    label = {'introduction_reading': 'Company introduction reading',
             'introduction_review': 'Company introduction semantic review',
             'introduction_content_repair': 'Company introduction content repair'}.get(stage, 'Company introduction')
    pages = ', '.join(map(str, details['source_pages']))
    location = f' on source pages {pages}' if pages else ''
    return f"{label} failed{location} ({details['operation']}, {details['kind']}): {details['message']}"
