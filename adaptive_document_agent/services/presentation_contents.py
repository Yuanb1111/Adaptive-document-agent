"""Measure a one-page agenda, retaining the complete labels in slide notes."""

from .text_capacity import wrap_copy


def contents_layout(entries, width, capacity):
    """Prefer complete two-column labels, with a readable 12 pt floor."""
    def measure(labels, columns, font):
        column_width = (width - 1.10 - .30 * (columns - 1)) / columns
        spacing = font * 1.22
        rows = [(n, label, max(.34, len(wrap_copy(label, column_width - .60, font))
                                    * spacing / 72 + .08)) for n, label in enumerate(labels, 1)]
        # Find contiguous column boundaries with the lowest maximum height.
        prefix = [0.0]
        for row in rows:
            prefix.append(prefix[-1] + row[2] + .08)
        states = {0: (0.0, [])}
        for _ in range(columns):
            following = {}
            for end in range(len(rows) + 1):
                choices = [(max(cost, prefix[end] - prefix[start] - (.08 if end > start else 0)),
                            cuts + [end]) for start, (cost, cuts) in states.items() if start <= end]
                following[end] = min(choices, key=lambda item: item[0])
            states = following
        height, cuts = states[len(rows)]
        groups, start = [], 0
        for end in cuts:
            groups.append(rows[start:end])
            start = end
        return height, groups, column_width, font, spacing

    options = [(2, n) for n in (16, 15, 14, 13, 12)] + [(3, 12)] if len(entries) <= 30 else []
    for columns, font in options:
        layout = measure(entries, columns, font)
        if layout[0] <= capacity:
            return layout[1:]
    # Pathological agendas still have exactly one page. Whole-word excerpts
    # point to complete notes; no authored label or analytical evidence is lost.
    visible = entries[:29] if len(entries) > 30 else entries
    if len(entries) > 30:
        visible = [*visible, f"{len(entries) - 29} further sections — see slide notes"]
    lines = max(1, int((capacity / max(1, (len(visible) + 2) // 3) - .16) / (14.64 / 72)))
    text_width = (width - 1.70) / 3 - .60
    compact = []
    for label in visible:
        words = label.split()
        while len(wrap_copy(" ".join(words) + "…", text_width, 12)) > lines and len(words) > 1:
            words.pop()
        while len(words) == 1 and len(wrap_copy(words[0] + "…", text_width, 12)) > lines and len(words[0]) > 1:
            words[0] = words[0][:-1]
        shortened = " ".join(words)
        compact.append(shortened + "…" if shortened != label else label)
    return measure(compact, 3, 12)[1:]
