"""Carry bounded supplementary reading into synthesis, including narrative-only evidence."""
import re

from adaptive_document_agent.models import ValidationIssue
from adaptive_document_agent.services.source_quotes import normalize_quote


def source_check_context(result):
    """Expose check statuses and independently verified quotes, never inferred facts."""
    coverage = result.profile.source_coverage
    pages = {p.page_number: p.text for p in result.document.pages}
    records, passages = [], {}
    remaining = 18_000
    for check in coverage.checks if coverage else []:
        record = dict(section_id=check.section_id, pages=check.pages, status=check.status,
                      question=check.reason, decision_impact=check.decision_impact,
                      finding=check.finding, evidence=[], context_complete=True)
        for page, quotes in check.evidence_quotes.items():
            for quote in quotes:
                words = quote.split()
                match = re.search(r'\s+'.join(re.escape(word) for word in words), pages.get(page, '')) if words else None
                if check.status != 'checked_found' or match is None:
                    record['context_complete'] = False
                    continue
                literal = match.group()
                if len(literal) > remaining:
                    record['context_complete'] = False
                    continue
                remaining -= len(literal)
                record['evidence'].append(dict(page=page, text=literal))
                passages.setdefault(page, []).append(literal)
        records.append(record)
    return records, passages


def uncited_source_checks(result, brief):
    """Literal referencing is an audit signal, never proof of semantic coverage."""
    records, _ = source_check_context(result)
    return [record for record in records if record['status'] == 'checked_found'
            and (not record['context_complete'] or not record['evidence']
                 or not any(q['page'] == cited.page
                            and normalize_quote(q['text']) in normalize_quote(cited.text)
                            for q in record['evidence'] for item in brief.items for cited in item.evidence))]


def record_uncited_checks(result, brief):
    for record in uncited_source_checks(result, brief):
        result.validation_warnings.append(ValidationIssue(
            code='source_check_not_referenced', stage='report', severity='warning',
            related_ids=[record['section_id']],
            message=f"Supplementary source check is not referenced by a literal brief quote. Original review question: {record['question']} "
                    f"Decision impact requiring review: {record['decision_impact']}. "
                    f"Physical pages: {record['pages']}. This is pending review, not certified absence or a passed business gate."))
