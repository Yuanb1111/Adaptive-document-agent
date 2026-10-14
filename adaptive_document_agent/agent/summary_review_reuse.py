"""Reuse an independent verdict only for byte-identical semantic evidence/copy."""
import json
from hashlib import sha256


def part_review_signatures(review, pages):
    signatures = {}
    from adaptive_document_agent.services.introduction_audience import audience_part_ids
    required = audience_part_ids(review)
    for part in review.parts:
        if part.id not in required:
            continue
        assigned = [dict(title=page.title, placement=page.placement,
                         item=item.model_dump(mode='json'))
                    for page in pages for item in page.items if part.id in item.part_ids]
        from .summary_coverage import required_meanings
        value = dict(source=part.model_dump(mode='json'), assigned=assigned,
                     required_meanings=required_meanings(review).get(part.id))
        signatures[part.id] = sha256(json.dumps(value, sort_keys=True,
            ensure_ascii=False).encode('utf-8')).hexdigest()
    return signatures


class AcceptedPartReviews:
    """Invocation-local ledger; never transfers verdicts between documents/runs."""
    def __init__(self):
        self.accepted = {}

    def retained(self, signatures, audit):
        reused = {pid: value for pid, value in self.accepted.items()
                  if signatures.get(pid) == value[0]}
        audit['retained_part_reviews'] = [dict(part_id=pid, signature=value[0],
            review_attempt=value[2], verdict=value[1].model_dump(mode='json'))
            for pid, value in reused.items()]
        return {pid: value[1] for pid, value in reused.items()}

    def remember(self, response, signatures, attempt):
        for verdict in response.parts:
            if verdict.accepted:
                self.accepted[verdict.part_id] = (signatures[verdict.part_id], verdict, attempt)
