"""Retain authored structure only for proven display-spelling changes."""
from adaptive_document_agent.models.summary_display import SummaryDisplay
from .translation_atoms import protect_quantities, restore_quantities


def _spelling(text):
    protected, atoms = protect_quantities(text, 'english')
    return restore_quantities(protected, atoms)


def summary_display(item, text):
    """Equivalent money spelling does not invent a new semantic layout.

    Compare the entire ordered prose and literal coefficients, not a bag of
    numbers. Rewording, changed signs/units/currencies and actual translation
    retain the conservative paragraph fallback. Old anchors are never applied
    to changed wording without checking their exact replacement.
    """
    if text == item.text:
        return item.display or SummaryDisplay()
    if item.display is None or ' '.join(_spelling(item.text).split()) != ' '.join(_spelling(text).split()):
        return SummaryDisplay()
    anchors, start = [], 0
    for anchor in item.display.break_after:
        replacement = anchor if anchor in text else _spelling(anchor)
        offset = text.find(replacement, start)
        if not replacement or text.count(replacement) != 1 or offset < 0:
            anchors = []
            break
        end = offset + len(replacement)
        if end < len(text) and not text[end].isspace():
            anchors = []
            break
        anchors.append(replacement)
        start = end
    return item.display.model_copy(update={'break_after': anchors})
