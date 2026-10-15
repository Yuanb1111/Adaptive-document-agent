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
    schema: type[Draft], *, cancelled: Event | None = None, allow_rewrite: bool = True,
) -> tuple[Draft, list[SummarySlidePage]]:
    """Pack retained copy; repair the physical body allocation independently."""
    attempts = audit.setdefault('layout_attempts', [])
    for attempt in range(2):
        record = {'attempt': attempt + 1}
        attempts.append(record)
        from .summary_draft_duplicates import deduplicate_draft
        draft = deduplicate_draft(draft, record)
        # Evidence-ID/coverage problems remain content errors. Only geometry
        # failures enter this independent layout budget.
        pages = expand(draft, catalog, review)
        over_budget = False
        try:
            pages = pack_theme_pages(pages)
            body_count = sum(page.placement == 'body' for page in pages)
            record['physical_groups'] = [dict(title=page.title, placement=page.placement,
                item_labels=[item.label for item in page.items], copy_characters=sum(len(item.text) for item in page.items))
                for page in pages]
            if review.max_intro_slides is not None and body_count > review.max_intro_slides:
                over_budget = True
                raise SummaryLayoutError(f'Body budget is {review.max_intro_slides} physical slides; '
                                         f'pagination produced {body_count}. Logical groups are not slides.')
            record.update(status='success', rendered_pages=len(pages))
            return draft, pages
        except SummaryLayoutError as exc:
            record.update(status='overflow', errors=[str(exc)], draft=draft.model_dump(mode='json'))
            if not allow_rewrite:
                raise SummaryDraftProtocolError('Additive omission correction exceeds verified physical layout: '+str(exc)) from exc
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
            if over_budget and review.audience_part_ids is not None:
                instruction += (' Preserve every independently selected required_meanings entry. '
                    'Use the measured physical_groups to resolve both overlong copy and stranded '
                    'logical-group continuations. Combine related claims into fewer concise paragraphs '
                    'and coherent groups; do not copy the full quoted evidence or repeat the same scope '
                    'in multiple items. A logical group is not a physical slide. There is no supporting '
                    'appendix for this whole-file budget. Short paragraphs are readability '
                    'guidance only, never a word-count constraint overriding selected meanings. '
                    'Update every item meaning_refs to its current literal text and exact owned '
                    'source bindings after combining or splitting copy. '
                    'Missing meaning will still fail the independent per-meaning review.')
            repair = list(messages) + [untrusted_document_message(json.dumps(record,ensure_ascii=False)),
                {'role':'user','content':instruction}]
            if over_budget and any(getattr(p, 'placement', 'body') == 'appendix' for p in draft.pages):
                from .summary_body_allocation import reallocate_body
                revised = reallocate_body(gateway, draft, repair, schema, record,
                                          limit=review.max_intro_slides, cancelled=cancelled)
            else:
                revised = author_draft(gateway, repair, schema, record, cancelled=cancelled)
            if revised == draft:
                raise SummaryDraftProtocolError('Layout repair repeated an overflowing draft')
            draft = revised
