"""One targeted correction after removing a rejected companion changes context."""
from adaptive_document_agent.services.llm.exceptions import LLMResponseError, LLMTransportError
from .brief_semantic_repair import correct_new_meaning_errors


def selection_context_repair(gateway, *, result, excerpts, topics, source_context,
                             evidence_catalog, semantic_validator, audit, cancelled=None):
    used = False

    def repair(brief, errors, original_indices):
        nonlocal used
        if used or not semantic_validator or not errors:
            return None
        used = True
        if any(type(i) is not int or not 0 <= i < len(brief.items) for i in errors):
            return None
        record = dict(original_indices=original_indices, initial_errors={
            f'item_{i}': ['Meaning review: ' + reason for reason in reasons]
            for i, reasons in errors.items()})
        audit['selection_context_correction'] = record
        try:
            corrected = correct_new_meaning_errors(gateway, brief, result=result, excerpts=excerpts,
                topics=topics, source_context=source_context, evidence_catalog=evidence_catalog,
                semantic_validator=semantic_validator, audit=record, cancelled=cancelled,
                editable_indices=set(errors))
        except LLMTransportError:
            raise
        except (LLMResponseError, ValueError) as exc:
            record['failure'] = str(exc)
            return None
        if corrected is None:
            return None
        # The correction API is text-only and independently reviews the whole
        # selection. Keep the item addresses and every currently passing lock.
        if (corrected.title != brief.title or len(corrected.items) != len(brief.items)
                or any(corrected.items[i] != item for i, item in enumerate(brief.items) if i not in errors)):
            return None
        return corrected

    return repair
