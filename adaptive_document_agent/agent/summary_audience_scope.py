"""Keep accepted audience assertions distinct from their complete evidence passages."""


def author_paragraph_guidance(audience_selected):
    display = (
        'Return a non-null display object and an explicit layout on EVERY item in this same writing pass: '
        'paragraphs for ordinary assertions, comparison for an explicit contrast, timeline for explicit '
        'chronology, relationship for explicitly stated links, or key_metrics for qualified reported facts. '
        'Choose from this actual content, never a document-type template. '
        'Choosing paragraphs is valid when a semantic visual structure is not supported. Keep text as the complete '
        'reviewable copy; supply break_after as unique literal statement-ending phrases, in order. '
        'Do not invent captions, categories, stages, dates, relationships or numbers for the layout. '
        'Keep each necessary attribution, denominator, period and qualification with its assertion. '
        'Several short visual paragraphs can share one item and its full meaning references, avoiding '
        'a separate repeated heading for every sentence. No extra model call is needed for layout. ')
    if audience_selected:
        return display + (
            'Choose paragraph lengths from the supplied physical allocation; there is no '
            'per-paragraph target length. One coherent paragraph may express multiple compatible '
            'distinct required meanings with ALL owning fact_ids and meaning_refs. Every separate '
            'item adds a labelled heading and spacing; minimize repeated label/body wording while '
            'retaining meaning carried by labels, complete assertions and all qualifications. '
            'The 6000-character item limit is transport capacity, not a writing target. ')
    return display + (
        'Use up to 32 complete items per group if necessary, target 160-240 Latin-equivalent characters each '
        '(CJK characters count as two). Keep complete sentences, attribution and material qualifications. '
        'The transport item text limit is 6000 characters; prefer complete concise paragraphs below 1200. ')


def selected_audience_scope(*, compression=False):
    rule = (
        'The independently accepted required_meanings inventory defines the audience content scope. '
        'Complete source parts, catalog facts and quotations are evidence for truth and necessary '
        'qualifications, NOT an additional audience checklist. Express ALL selected assertions, '
        'including every selected number, named activity, contrast and necessary period, basis, '
        'attribution, uncertainty or condition. Do not add an independent assertion merely because '
        'it appears in the same complete source passage or is covered by a retained fact ID. '
        'Do not expand an accepted assertion with unrelated source statistics, examples or details. '
        'A source-supported qualification needed to make a selected assertion accurate remains '
        'mandatory even when the short inventory wording does not repeat it. The model must judge '
        'that semantic relationship; a word limit or page limit cannot authorize its removal. ')
    if compression:
        rule += (
            'Existing writer copy may contain incidental independent assertions outside this accepted '
            'scope. You MAY remove ONLY those unselected independent assertions which are not necessary '
            'qualifiers of a selected meaning. Do not freeze such extras merely because they are true '
            'or appeared in an earlier draft. Preserve ALL original fact IDs and exact source provenance '
            'even when incidental audience prose is removed. Never drop a selected meaning, disguise '
            'a necessary qualification as an extra, or claim that citations alone establish coverage. ')
    return rule + ('The complete current selected meaning union still requires fresh independent '
                   'source and per-meaning semantic review; these instructions grant no acceptance.')
