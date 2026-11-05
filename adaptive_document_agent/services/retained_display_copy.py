"""Recognize exact source-authored copy before applying legacy chart captions."""


def is_source_authored_message(result, slide):
    """Keep the selected draft visible; publication gates still review it.

    This recognizes authoring provenance, not semantic approval. A changed or
    unrelated message cannot acquire provenance from another selected page.
    """
    from adaptive_document_agent.agent.retained_analysis import selected_record
    record = selected_record(result)
    if not record or not record.get('source_authoring') or len(slide.insight_ids) != 1:
        return False
    decisions = record.get('selection', {}).get('decisions', [])
    message = slide.message.strip()
    def retained_prefix(original):
        # Budget planning can retain a leading sequence of complete sentences.
        # Preserve that actual current copy, without restoring removed detail.
        return bool(message and isinstance(original, str) and (original == message
                    or message.endswith(('.', '!', '?', '。', '！', '？')) and original.startswith(message + ' ')))
    return any(d.get('insight_id') == slide.insight_ids[0] and d.get('decision') == 'include'
               and retained_prefix(d.get('page', {}).get('message'))
               for d in decisions if isinstance(d, dict) and isinstance(d.get('page'), dict))
