"""Exact visible paragraph addresses, independent of source-language quotations."""


def visible_paragraphs(pages):
    paragraphs, groups = {}, {}
    for p, page in enumerate(pages):
        for i, item in enumerate(page.items):
            identifier = f'v{p}_i{i}'
            group = getattr(item, 'continuation_group', '')
            if group:
                identifier = groups.setdefault(group, identifier)
            row = paragraphs.setdefault(identifier, {'paragraph_id': identifier, 'part_ids': set(item.part_ids), 'segments': []})
            row['part_ids'].intersection_update(item.part_ids)
            row['segments'].append((getattr(item, 'continuation_index', 0), item.text))
    return {key: {'paragraph_id': key, 'part_ids': sorted(row['part_ids']),
                  'text': ''.join(text for _, text in sorted(row['segments']))}
            for key, row in paragraphs.items()}
