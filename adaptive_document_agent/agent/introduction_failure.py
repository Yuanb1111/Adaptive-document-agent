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
        break
    return stage, details


def introduction_failure_message(stage, details):
    label = 'Company introduction reading' if stage == 'introduction_reading' else 'Company introduction'
    pages = ', '.join(map(str, details['source_pages']))
    location = f' on source pages {pages}' if pages else ''
    return f"{label} failed{location} ({details['operation']}, {details['kind']}): {details['message']}"
