"""Reconcile exhaustive claims with an explicitly enumerated source partition.

The model chooses the topic. This bounded check can complete that chosen scope
only when literal source labels, retained cells and totals independently agree.
It never interprets a familiar geography name or changes an observation.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re

from adaptive_document_agent.models import SourceEvidence, ValidationIssue


@dataclass(frozen=True)
class DeclaredScope:
    labels: tuple[str, ...]
    definitions: tuple[tuple[str, str], ...]
    paragraph: str
    page: int


def _key(text: str) -> str:
    text = re.sub(r'(?i)^sub\s*total\s+(?:of\s+)?', '', text.strip())
    return ' '.join(re.findall(r'[^\W_]+', text.casefold()))


def _declared_scopes(page):
    for raw in re.split(r'\n\s*\n', page.text):
        paragraph = ' '.join(raw.split())
        matches = list(re.finditer(r'\((\d{1,2})\)\s*', paragraph))
        if not 3 <= len(matches) <= 12 or [int(m[1]) for m in matches] != list(range(1, len(matches) + 1)):
            continue
        labels, definitions = [], []
        for i, match in enumerate(matches):
            clause = paragraph[match.end():matches[i + 1].start() if i + 1 < len(matches) else len(paragraph)]
            label = re.split(r',|;|\.|\bwhich\b', clause, maxsplit=1, flags=re.I)[0].strip()
            if not label or len(label) > 100:
                break
            labels.append(label)
            # Preserve the source's explicit exclusion boundary, not a guessed
            # association between well-known categories.
            definition = re.match(r'\s*' + re.escape(label) + r',?\s+which\s+(?:refer[s]?\s+to|means?|comprise[s]?)\s+(.+?)(?=\.|$)', clause, re.I)
            if definition and re.search(r'\b(?:other than|except|excluding)\b', definition[1], re.I):
                definitions.append((label, label + ': ' + definition[1].strip(' ,;') + '.'))
        if len(labels) == len(matches) and len({_key(label) for label in labels}) == len(labels):
            yield DeclaredScope(tuple(labels), tuple(definitions), paragraph, page.page_number)


def _row(items):
    labels = {e.row_label for item in items for e in item.evidence if e.row_label}
    return _key(next(iter(labels))) if len(labels) == 1 else ''


def _signature(items):
    values = {(o.unit, o.currency, o.unit_scale, o.raw_unit, o.entity, o.period_type, o.period_basis,
               tuple(sorted(o.category_dimensions.items()))) for o in items}
    return next(iter(values)) if len(values) == 1 else None


def _valid_cells(items, table, periods):
    if len(items) != len(periods) or {o.period for o in items} != periods:
        return False
    for item in items:
        row, column = item.row_id, item.column_id
        if (item.value is None or not math.isfinite(item.value) or item.validation_status != 'valid'
                or item.anomaly_notes or row is None or column is None
                or not 0 <= row < len(table.rows) or not 0 < column < len(table.rows[row].cells)):
            return False
        source = table.rows[row]
        if (source.alignment_status != 'resolved' or source.cells[column] != item.raw_value
                or column >= len(table.column_periods) or table.column_periods[column] != item.period
                or not any(e.table_id == table.table_id and e.page == source.page
                           and e.row_label == source.cells[0] for e in item.evidence)):
            return False
    return True


def declared_scope_series(result, observations):
    """Retain exact-table series when a repeated row name has other meanings.

    A literal numbered source scope supplies the category boundary. This is a
    presentation view of existing IDs, never a mutation of source facts or a
    licence to merge same-label values from different tables.
    """
    from collections import defaultdict
    from adaptive_document_agent.document_model import period_sort_key

    for page in result.document.pages:
        for scope in _declared_scopes(page):
            labels = {_key(label) for label in scope.labels}
            for table in page.tables:
                table_rows = {_key(row.cells[0] or '') for row in table.rows if row.cells}
                if not labels <= table_rows or 'total' not in table_rows:
                    continue
                groups = defaultdict(list)
                for item in observations:
                    if item.effective_table_id == table.table_id and _row([item]) in labels | {'total'}:
                        groups[(_row([item]), _signature([item]))].append(item)
                for group in groups.values():
                    periods = {item.period for item in group}
                    if len(periods) >= 2 and None not in periods and _valid_cells(group, table, periods):
                        yield sorted(group, key=lambda item: period_sort_key(item.period))


def _completed_family(scope, selected, lookup, table):
    periods = {o.period for group in selected for o in group}
    signature = _signature([o for group in selected for o in group])
    if not periods or None in periods or signature is None:
        return None
    family = {}
    for label in scope.labels:
        candidates = [(sid, group) for sid, group in lookup.items()
                      if _row(group) == _key(label) and _signature(group) == signature
                      and {o.effective_table_id for o in group} == {table.table_id}
                      and _valid_cells(group, table, periods)]
        # Equivalent duplicate source series may differ in row/period scope;
        # none is silently preferred at this recovery boundary.
        if len(candidates) != 1:
            return None
        family[label] = candidates[0]
    totals = [group for group in lookup.values()
              if _row(group) == 'total' and _signature(group) == signature
              and {o.effective_table_id for o in group} == {table.table_id}
              and _valid_cells(group, table, periods)]
    if totals:
        if len(totals) != 1:
            return None
        for total in totals[0]:
            amount = sum(next(o.value for o in group if o.period == total.period) for _, group in family.values())
            if not math.isclose(amount, total.value, rel_tol=1e-9, abs_tol=1e-8):
                return None
    else:
        # Extraction may retain the exact table total but omit a redundant
        # total Observation. Use that raw cell only as a consistency check;
        # never create a new observation or infer a missing category value.
        from adaptive_document_agent.extraction.numeric_parser import parse_number
        rows = [row for row in table.rows if row.cells and _key(row.cells[0] or '') == 'total'
                and row.alignment_status == 'resolved']
        if len(rows) != 1:
            return None
        for period in periods:
            members = [next(o for o in group if o.period == period) for _, group in family.values()]
            columns = {o.column_id for o in members}
            if len(columns) != 1:
                return None
            column = next(iter(columns))
            if column >= len(rows[0].cells):
                return None
            total = parse_number(rows[0].cells[column] or '')
            parts = [parse_number(o.raw_value) for o in members]
            if (total is None or total.scale != 1 or total.currency is not None
                    or any(p is None or p.scale != 1 or p.currency is not None for p in parts)):
                return None
            if any(not math.isclose(p.value * (o.unit_scale or 1), o.value,
                                    rel_tol=1e-9, abs_tol=1e-8) for p, o in zip(parts, members)):
                return None
            if not math.isclose(sum(p.value for p in parts), total.value, rel_tol=1e-9, abs_tol=1e-8):
                return None
    return family


def _audit(result, topic, scope, code, message):
    if any(w.code == code and w.related_ids == [topic.id] for w in result.validation_warnings):
        return
    result.validation_warnings.append(ValidationIssue(code=code, stage='presentation',
        severity='info' if code.endswith('completed') else 'warning', related_ids=[topic.id],
        message=message, evidence=[SourceEvidence(page=scope.page, text=scope.paragraph,
                                                extraction_method='digital_text', confidence=1.0)]))


def _requests_complete_scope(topic, scope, table):
    """Bind a universal quantifier to the source partition, not its subset."""
    text = topic.title + ' ' + topic.takeaway
    if re.search(r'\b(?:except|excluding|other than|all\s+but|not\s+all)\b', text, re.I):
        return False
    if re.search(r'\b(?:selected|partial|subset|chosen|some|certain|sampled|sample|observed)\b', text, re.I):
        return False
    from adaptive_document_agent.extraction.comparison_context import _caption_subject
    caption = _caption_subject(table.model_copy(update={'raw_header_lines': [scope.paragraph]})) or ''
    partition = re.split(r'\bby\b', caption, flags=re.I)
    if len(partition) != 2:
        return bool(re.search(r'\b(?:complete|entire)\s+(?:source\s+)?breakdown\b', text, re.I))
    nouns = []
    for part in re.split(r'[/,]|\band\b|\bor\b', partition[1], flags=re.I):
        words = re.findall(r'[A-Za-z-]+', part)
        if words:
            word = words[-1].lower()
            stem = word[:-3] + 'y' if word.endswith('ies') else word.rstrip('s')
            nouns.append(re.escape(stem[:-1]) + '(?:y|ies)' if stem.endswith('y') else re.escape(stem) + 's?')
    return bool(nouns and re.search(r'\b(?:all|every|entire|complete)\s+(?:[A-Za-z-]+\s+){0,3}(?:'
                                   + '|'.join(nouns) + r')\b', text, re.I))


def reconcile_source_scopes(result, lookup=None) -> set[str]:
    """Complete only requested exhaustive, source-declared and reconciled scopes.

    A partial model selection remains partial. Explicit omission decisions and
    unresolved source cells are respected, and an exhaustive title is narrowed
    with an observable warning rather than filled with guessed observations.
    """
    if result.presentation_topics is None:
        return set()
    if lookup is None:
        from adaptive_document_agent.agent.presentation_topic_selector import series_directory
        _, lookup = series_directory(result)
    tables = {t.table_id: t for p in result.document.pages for t in p.tables}
    scopes = [(p.page_number, scope) for p in result.document.pages for scope in _declared_scopes(p)]
    changed = set()
    for topic in result.presentation_topics.topics:
        selected = [lookup[sid] for sid in topic.series_ids if sid in lookup]
        if len(selected) != len(topic.series_ids) or len(selected) < 2:
            continue
        table_ids = {o.effective_table_id for group in selected for o in group}
        if len(table_ids) != 1 or next(iter(table_ids)) not in tables:
            continue
        table = tables[next(iter(table_ids))]
        rows = {_row(group) for group in selected}
        matches = [scope for page, scope in scopes if page == table.page and rows <= {_key(n) for n in scope.labels}]
        if len(matches) != 1 or '' in rows:
            continue
        scope = matches[0]
        previous = topic.model_dump_json()
        exhaustive = _requests_complete_scope(topic, scope, table)
        missing = {_key(label) for label in scope.labels} - rows
        if exhaustive and missing:
            family = _completed_family(scope, selected, lookup, table)
            omitted = {item.series_id for item in result.presentation_topics.omissions}
            if family and not any(sid in omitted for sid, _ in family.values()):
                topic.series_ids = [sid for sid, _ in family.values()]
                from adaptive_document_agent.extraction.comparison_context import _caption_subject
                caption = _caption_subject(table.model_copy(update={'raw_header_lines': [scope.paragraph]}))
                topic.title = caption[:1].upper() + caption[1:] if caption else 'Complete source breakdown'
                topic.question = 'How do the reported values compare across the complete source breakdown?'
                topic.takeaway = ''  # A restored category cannot inherit another category's direction.
                _audit(result, topic, scope, 'presentation_source_scope_completed',
                       'Completed the selected exhaustive scope from its literal source enumeration and reconciled total.')
            else:
                for field in ('title', 'takeaway'):
                    setattr(topic, field, re.sub(r'\b(?:all(?:\s+major)?|every|complete|entire)\b',
                                                'selected', getattr(topic, field), flags=re.I))
                disclosure = 'Selected categories only; the full source breakdown could not be verified for this display.'
                if disclosure not in topic.caveats and len(topic.caveats) < 3:
                    topic.caveats.append(disclosure)
                _audit(result, topic, scope, 'presentation_source_scope_incomplete', disclosure)
        for label, definition in scope.definitions:
            if _key(label) not in {_row(lookup[sid]) for sid in topic.series_ids}:
                continue
            if definition not in topic.question:
                topic.question += ' ' + definition
            if definition not in topic.caveats and len(topic.caveats) < 3:
                topic.caveats.append(definition)
        if topic.model_dump_json() != previous:
            changed.add(topic.id)
    return changed


def prepare_cached_source_scopes(result) -> bool:
    """Recompile only affected cached topics on a copy, retaining unrelated work.

    This is a deterministic replay of retained source evidence, not a new model
    analysis. A failed compilation leaves the caller's selected scope and deck
    intact and adds an actionable diagnostic instead of bypassing validation.
    """
    if result.presentation_plan is None or result.presentation_topics is None:
        return False
    snapshot = result.model_copy(deep=True)
    affected = reconcile_source_scopes(snapshot)
    if not affected:
        return False
    from adaptive_document_agent.agent.topic_plan_compiler import compile_topic_plan
    from adaptive_document_agent.agent.presentation_summary_selection import rebuild_selected_topic_summary
    from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator
    try:
        selected = snapshot.presentation_topics.model_copy(deep=True)
        rebuilt = compile_topic_plan(snapshot)
        snapshot.presentation_topics = selected
        plan = result.presentation_plan.model_copy(deep=True)
        replacements = {theme.id: theme for theme in rebuilt.themes if theme.id in affected}
        if set(replacements) != affected:
            raise ValueError('A changed source scope did not produce a validated analytical theme.')
        plan.themes = [replacements.get(theme.id, theme) for theme in plan.themes]
        replacement_slides = {key: [slide for slide in rebuilt.slides
                                  if slide.slide_type == 'analysis' and slide.theme_id == key]
                              for key in affected}
        slides, inserted = [], set()
        for slide in plan.slides:
            if slide.slide_type == 'analysis' and slide.theme_id in affected:
                if slide.theme_id not in inserted:
                    slides.extend(replacement_slides[slide.theme_id])
                    inserted.add(slide.theme_id)
            else:
                slides.append(slide)
        if inserted != affected:
            raise ValueError('Changed source scope has no existing analytical display to replace.')
        plan.slides = slides
        rebuild_selected_topic_summary(snapshot, plan)
        # The summary may restore duplicate references from raw topic evidence.
        # Reuse the existing exact-source alignment before validation.
        from adaptive_document_agent.validation.presentation_evidence_alignment import align_redundant_slide_evidence
        alignment_notes = align_redundant_slide_evidence(plan, snapshot.observations, snapshot.charts)
        plan.editorial_notes = list(dict.fromkeys([*plan.editorial_notes, *alignment_notes,
            'Recompiled affected source-category scopes from retained evidence without a model request.']))
        PresentationPlanValidator().validate(plan, snapshot)
    except ValueError as exc:
        code = 'presentation_source_scope_replay_failed'
        if not any(w.code == code and w.related_ids == sorted(affected) for w in result.validation_warnings):
            result.validation_warnings.append(ValidationIssue(code=code, stage='presentation', severity='warning',
                related_ids=sorted(affected), message='Source-bound category replay failed validation: ' + str(exc)))
        return False
    result.presentation_topics = selected
    result.presentation_plan = plan
    result.charts = snapshot.charts
    result.validation_warnings = snapshot.validation_warnings
    return True
