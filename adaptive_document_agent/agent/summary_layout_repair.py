"""Pagination and bounded layout repair, independent of content revision."""
from collections.abc import Callable
from threading import Event
from typing import Any, TypeVar

from pydantic import BaseModel

from adaptive_document_agent.models.summary import SummaryReview, SummarySlidePage
from adaptive_document_agent.services.llm.gateway import LLMGateway

from .summary_draft_protocol import SummaryDraftProtocolError
from .summary_theme_layout import pack_theme_pages, SummaryLayoutError
from .summary_layout_feedback import (layout_feedback, compression_progress,
    compression_binding_errors, selected_meaning_source)

Draft = TypeVar('Draft', bound=BaseModel)


def paginate_draft(
    gateway: LLMGateway, draft: Draft, catalog: dict, review: SummaryReview,
    messages: list[dict[str, str]], audit: dict[str, Any],
    expand: Callable[[Draft, dict, SummaryReview], list[SummarySlidePage]],
    schema: type[Draft], *, cancelled: Event | None = None, allow_rewrite: bool = True,
) -> tuple[Draft, list[SummarySlidePage]]:
    """Pack retained copy; permit two measured, source-preserving audience compressions."""
    attempts = audit.setdefault('layout_attempts', [])
    original = draft.model_copy(deep=True)
    selected = review.audience_part_ids is not None
    # The legacy complete-reading contract keeps its existing single repair.
    # Audience synthesis has a mandatory meaning inventory and one additional
    # correction for a measured, but insufficient, physical compression.
    repair_limit = 2 if selected else 1
    previous_feedback = None
    original_feedback, original_physical_groups = None, []
    for attempt in range(repair_limit + 1):
        record = {'attempt': attempt + 1}
        attempts.append(record)
        from .summary_draft_duplicates import deduplicate_draft
        draft = deduplicate_draft(draft, record)
        if not attempt:
            original = draft.model_copy(deep=True)
        from .summary_authored_coverage import authored_coverage_errors
        protected_errors = compression_binding_errors(draft, original, catalog) if attempt else []
        if attempt and getattr(draft.pages[0], 'placement', 'body') != 'body':
            protected_errors.append('Layout compression moved the opening outside the presentation body')
        if selected and attempt:
            if any(getattr(page, 'placement', 'body') != 'body' for page in draft.pages):
                protected_errors.append('Selected introduction layout compression cannot create supporting appendices')
        coverage_errors = (authored_coverage_errors(draft, selected_meaning_source(review), catalog, record)
                           if selected else [])
        if selected and not attempt and coverage_errors:
            record['initial_authored_coverage_errors'] = coverage_errors
        binding_errors = protected_errors + (coverage_errors if attempt else [])
        if binding_errors:
            record.update(status='source_invalid', errors=binding_errors,
                          draft=draft.model_dump(mode='json'))
            audit['draft'] = record['draft']
            if 'authored_meaning_coverage' in record:
                audit['authored_meaning_coverage'] = record['authored_meaning_coverage']
            from .summary_layout_recovery import missing_meanings_only, restore_selected_meanings
            if (selected and attempt < repair_limit and allow_rewrite and not protected_errors
                    and missing_meanings_only(coverage_errors)):
                draft = restore_selected_meanings(gateway, original, draft, catalog, review, record, schema,
                    original_feedback=original_feedback, original_physical_groups=original_physical_groups,
                    repair_limit=repair_limit, cancelled=cancelled)
                previous_feedback = record['layout_feedback']
                continue
            raise SummaryDraftProtocolError('Layout compression violated source preservation: ' +
                                            '; '.join(binding_errors))
        # Evidence-ID/coverage problems remain content errors. Only geometry
        # failures enter this independent layout budget.
        over_budget = False
        try:
            pages = expand(draft, catalog, review)
            pages = pack_theme_pages(pages)
            body_count = sum(page.placement == 'body' for page in pages)
            record['physical_groups'] = [dict(title=page.title, placement=page.placement,
                item_labels=[item.label for item in page.items], copy_characters=sum(len(item.text) for item in page.items))
                for page in pages]
            feedback = layout_feedback(draft, pages, review, catalog)
            record['layout_feedback'] = feedback
            if not attempt:
                original_feedback, original_physical_groups = feedback, record['physical_groups']
            if previous_feedback is not None:
                record['compression_progress'] = compression_progress(previous_feedback, feedback)
            if review.max_intro_slides is not None and body_count > review.max_intro_slides:
                over_budget = True
                raise SummaryLayoutError(f'Body budget is {review.max_intro_slides} physical slides; '
                                         f'pagination produced {body_count}. Logical groups are not slides.')
            record.update(status='success', rendered_pages=len(pages))
            return draft, pages
        except SummaryLayoutError as exc:
            record.update(status='overflow', errors=[str(exc)], draft=draft.model_dump(mode='json'))
            from adaptive_document_agent.services.compact_summary import compact_title_errors, compact_heading_errors
            title_errors = [error for page in draft.pages for error in compact_title_errors(page.title)]
            heading_errors = [error for page in draft.pages for item in page.items
                              for error in compact_heading_errors(item.label)]
            if title_errors:
                record['title_errors'] = title_errors
            if heading_errors:
                record['paragraph_heading_errors'] = heading_errors
            if 'layout_feedback' not in record:
                record['layout_feedback'] = layout_feedback(draft, None, review, catalog)
                if previous_feedback is not None:
                    record['compression_progress'] = compression_progress(previous_feedback, record['layout_feedback'])
            if not attempt and original_feedback is None:
                original_feedback = record['layout_feedback']
            initial_coverage_errors = record.get('initial_authored_coverage_errors', [])
            record['errors'].extend(initial_coverage_errors)
            if not allow_rewrite:
                raise SummaryDraftProtocolError('Additive omission correction exceeds verified physical layout: '+str(exc)) from exc
            if attempt == repair_limit:
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
            if title_errors and not initial_coverage_errors:
                instruction = ('Repair only the overflowing logical group titles. The native template '
                    'allows at most THREE title lines at Arial 32 in an 8.91-inch text region. '
                    'Use short, faithful headings for the same supported subjects. The layout_feedback '
                    'identifies each title and its measured wrapping; paragraph capacity is not yet '
                    'a completed physical pagination result. Keep every complete body paragraph, label, '
                    'placement, original fact ID, meaning-ref addresses and exact document identity unchanged. '
                    'Do not split or shorten body text to fix a title. Preserve all supported claims '
                    'and required meanings; the final independently verified physical page budget '
                    'still applies after the corrected titles are measured.')
            elif heading_errors and not initial_coverage_errors:
                instruction = ('Repair only the overflowing paragraph labels identified by '
                    'layout_feedback.heading_errors. The native full-width paragraph heading allows '
                    'at most TWO lines at Arial 18, including its 00 numbering prefix. Use short '
                    'faithful labels for the same supported claims. Keep every complete body paragraph, '
                    'logical group title, placement, original fact ID, meaning-ref addresses and exact document '
                    'identity unchanged. Do not split or shorten body text to fix a label. Preserve '
                    'all claims and required meanings. The physical slide budget and independent '
                    'source/meaning verification still apply after the corrected labels are measured.')
            elif selected:
                from .summary_audience_scope import selected_audience_scope
                instruction = (
                    'Repair physical allocation and complete current paragraphs within the accepted '
                    'audience meaning scope. Combine related selected assertions and remove redundant '
                    'wording; retain the supported opening and every original fact ID. ' +
                    selected_audience_scope(compression=True))
            if selected and initial_coverage_errors:
                instruction += (' The ORIGINAL authored copy is structurally incomplete for the accepted '
                    'meaning inventory; authored_coverage_diagnostics lists its exact missing or invalid '
                    'references. Restore already-selected assertions absent from that copy using their '
                    'complete owning source passages while compressing. Restore visible meaning and '
                    'necessary qualifications, not just reference metadata. Every original fact ID '
                    'and the protected identity remain locked. No independent unselected assertion '
                    'may be added, and the complete final copy still requires fresh independent review.')
            if over_budget and review.audience_part_ids is not None:
                instruction += (' Preserve every independently selected required_meanings entry. '
                    'Use the measured physical_groups to resolve both overlong copy and stranded '
                    'logical-group continuations. Combine related claims into fewer concise paragraphs '
                    'and coherent groups; do not copy the full quoted evidence or repeat the same scope '
                    'in multiple items. A logical group is not a physical slide. There is no supporting '
                    'appendix for this whole-file budget. Short paragraphs are readability '
                    'guidance only, never a word-count constraint overriding selected meanings. '
                    'Update every item meaning_refs address mapping to the current paragraph actually '
                    'expressing that meaning, with its exact owned source bindings, after combining '
                    'or splitting copy. Return only part_id and meaning_index; Python binds full exact '
                    'current paragraph text and does not select or infer any mapping. '
                    'Missing meaning will still fail the independent per-meaning review.')
                instruction += (' The layout_feedback contains exact template font sizes, title wrapping, '
                    'full-width paragraph heights, per-group body capacity, every selected meaning '
                    'and its current literal paragraph references. These are mechanical measurements, '
                    'never semantic approval. Check every required meaning against the current copy. '
                    'Combine semantically equivalent repeated statements into one concise statement '
                    'with ALL their original owning fact IDs and meaning_refs. Shared literal quotes '
                    'and repeated source ownership are prompts for your semantic inspection, not '
                    'permission to assume equivalence. Preserve distinct selected numbers, necessary '
                    'qualifiers, scope and assertions. You may reorder related complete paragraphs into coherent groups '
                    'and shorten headings, while retaining the supported business opening. '
                    'Use the measured paragraph and heading costs to reduce PHYSICAL slides, rather '
                    'than only reducing paragraph count. Do not repeat the same attribution, business '
                    'definition or claim merely because multiple source parts support it. Preserve '
                    'all original fact IDs and exact document identity fields. All material meaning '
                    'still requires a fresh independent semantic review after geometry succeeds.')
                instruction += (' Use physical_allocation.target_physical_slides as the total slot '
                    'budget, and inspect physical_pages plus groups.current_physical_slides. '
                    'Reserve one slot for EACH new logical group, then allocate the remaining '
                    'continuation slots deliberately. If all slots are consumed by group starts, '
                    'every group must fit one slide; regroup or synthesize its supported assertions '
                    'across groups instead of leaving an oversized group to spill onto extra pages. '
                    'Full-width remaining height and native-grid cell loads are alternative layouts; '
                    'never add their capacities together. Retain every required meaning even when '
                    'the measured cap cannot be met, so the final guard can fail transparently.')
                if attempt:
                    progress = record.get('compression_progress', {})
                    instruction += (' This is the FINAL bounded physical compression correction. '
                        + ('The previous revision did not improve the measured geometry. '
                           if not progress.get('improved') else
                           'The previous revision improved geometry but still exceeds the hard page budget. ')
                        + 'Reconsider the grouping and repetitive wording across ALL selected parts; '
                        'a cosmetic rewrite or fewer logical groups alone is insufficient. '
                        'If all mandatory meanings cannot fit readably, retain them and fail transparently; '
                        'never solve the budget by removing a meaning, evidence binding or qualification.')
            record['compression_round'] = attempt + 1
            record['compression_round_limit'] = repair_limit
            choices = {}
            if (selected and over_budget and attempt == repair_limit - 1
                    and not record.get('compression_progress', {}).get('improved', True)):
                from .summary_layout_choices import layout_choices
                choices = layout_choices(draft, catalog, review, expand)
            if choices:
                from .summary_layout_choices import choose_layout
                revised = choose_layout(gateway, draft, catalog, review, record, choices, schema,
                                        cancelled=cancelled)
            elif over_budget and any(getattr(p, 'placement', 'body') == 'appendix' for p in draft.pages):
                from .summary_body_allocation import reallocate_body
                revised = reallocate_body(gateway, draft, [], schema, record,
                                          limit=review.max_intro_slides, cancelled=cancelled)
            else:
                from .summary_layout_patch import compress_pages
                revised = compress_pages(gateway, draft, catalog, record, instruction, schema,
                                         cancelled=cancelled, audience_selected=selected)
            if revised == draft and not selected:
                raise SummaryDraftProtocolError('Layout repair repeated an overflowing draft')
            previous_feedback = record.get('layout_feedback')
            draft = revised
