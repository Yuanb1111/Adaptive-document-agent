"""Pagination and bounded layout repair, independent of content revision."""
import json
from collections.abc import Callable
from threading import Event
from typing import Any, TypeVar

from pydantic import BaseModel

from adaptive_document_agent.models.summary import SummaryReview, SummarySlidePage
from adaptive_document_agent.services.llm.gateway import LLMGateway

from .prompting import untrusted_document_message
from .summary_draft_protocol import author_draft, SummaryDraftProtocolError
from .summary_theme_layout import pack_theme_pages, SummaryLayoutError

Draft = TypeVar('Draft', bound=BaseModel)


def paginate_draft(
    gateway: LLMGateway, draft: Draft, catalog: dict, review: SummaryReview,
    messages: list[dict[str, str]], audit: dict[str, Any],
    expand: Callable[[Draft, dict, SummaryReview], list[SummarySlidePage]],
    schema: type[Draft], *, cancelled: Event | None = None,
) -> tuple[Draft, list[SummarySlidePage]]:
    """Pack retained copy; repair the physical body allocation independently."""
    attempts = audit.setdefault('layout_attempts', [])
    for attempt in range(2):
        record = {'attempt': attempt + 1}
        attempts.append(record)
        # Evidence-ID/coverage problems remain content errors. Only geometry
        # failures enter this independent layout budget.
        pages = expand(draft, catalog, review)
        over_budget = False
        try:
            pages = pack_theme_pages(pages)
            body_count = sum(page.placement == 'body' for page in pages)
            if review.max_intro_slides is not None and body_count > review.max_intro_slides:
                over_budget = True
                raise SummaryLayoutError(f'Body budget is {review.max_intro_slides} physical slides; '
                                         f'pagination produced {body_count}. Logical groups are not slides.')
            record.update(status='success', rendered_pages=len(pages))
            return draft, pages
        except SummaryLayoutError as exc:
            record.update(status='overflow', errors=[str(exc)], draft=draft.model_dump(mode='json'))
            if attempt:
                raise SummaryDraftProtocolError('Summary layout repair exhausted: '+str(exc)) from exc
            instruction = (f'Repair the physical body allocation, aiming for at most {2 * review.max_intro_slides} '
                 'concise body paragraphs in total. Combine related core points. If the user and schema '
                 'allow a supporting appendix, move complete detailed supporting items there; keep the '
                 'business/subject opening in the body. Preserve every supported claim, source part and '
                 'fact ID across the combined body and appendix. Do not merely rename long body groups.'
                 if over_budget else 'Repair only overlong individual paragraphs: split them into complete '
                 'shorter items, preserving every claim, qualification, number, period, unit and fact ID. '
                 'Keep other content intact. Do not omit a source part. Python handles slide pagination; '
                 'do not compress a whole theme to fit one slide.')
            repair = list(messages) + [untrusted_document_message(json.dumps(record,ensure_ascii=False)),
                {'role':'user','content':instruction}]
            if over_budget and any(getattr(p, 'placement', 'body') == 'appendix' for p in draft.pages):
                from .summary_body_allocation import reallocate_body
                revised = reallocate_body(gateway, draft, repair, schema, record, cancelled=cancelled)
            else:
                revised = author_draft(gateway, repair, schema, record, cancelled=cancelled)
            if revised == draft:
                raise SummaryDraftProtocolError('Layout repair repeated an overflowing draft')
            draft = revised
