"""Validate supporting measures against retained model choices and source relations.

This boundary applies to slide scope only. Chart captions still use the strict
metric matcher with their own context, independently of supporting relations.
"""

from dataclasses import dataclass
import math
import re

from adaptive_document_agent.document_model.topic_matcher import is_positive_topic_mismatch


def _normal(text):
    text = re.sub(r"\([^)]*\)", " ", text)
    return " ".join(re.findall(r"[^\W_]+", text.casefold())).replace("expenses", "expense")


def _labels(observation):
    labels = [e.row_label for e in observation.evidence if e.row_label]
    labels.append(observation.metric_original.split(":", 1)[0])
    return list(dict.fromkeys(_normal(label) for label in labels if _normal(label)))


def _names(observation, text):
    text = f" {_normal(text)} "
    return any(f" {label} " in text or
               (label.endswith(" expense") and f" {label[:-8]} " in text)
               for label in _labels(observation))


@dataclass(frozen=True)
class SourceTopicRelation:
    kind: str
    observation_ids: tuple[str, ...]
    source_pages: tuple[int, ...]
    source_quote: str = ""


class TopicRelationValidator:
    """A declared support role needs its own numeric or quoted source proof."""

    def __init__(self, result):
        self.result = result
        self.observations = {o.id: o for o in result.observations}
        self.topics = {t.id: t for t in result.presentation_topics.topics} if result.presentation_topics else {}
        self.themes = {t.id: t for t in result.presentation_plan.themes} if result.presentation_plan else {}
        self.pages = {p.page_number: p for p in result.document.pages}
        self._lookup = None

    def mismatch(self, observation, slide, *, is_supporting_kpi=False):
        return (is_positive_topic_mismatch(observation, slide, is_supporting_kpi=is_supporting_kpi)
                and self.relation(observation, slide) is None)

    @staticmethod
    def _valid(item):
        return (item.value is not None and math.isfinite(item.value) and item.period
                and item.evidence and item.validation_status == "valid" and not item.anomaly_notes)

    def relation(self, observation, slide):
        topic, theme = self.topics.get(slide.theme_id), self.themes.get(slide.theme_id)
        if not topic or not theme or not self._valid(observation):
            return None
        declared = " ".join((topic.question, topic.rationale, topic.takeaway))
        if observation.id not in theme.observation_ids or not _names(observation, declared):
            return None
        if self._lookup is None:
            from adaptive_document_agent.agent.presentation_topic_selector import series_directory
            _, self._lookup = series_directory(self.result)
        selected = {o.id for sid in topic.series_ids for o in self._lookup.get(sid, [])}
        if observation.id not in selected:
            return None
        anchors = [self.observations[oid] for oid in theme.observation_ids
                   if oid in selected and oid in self.observations
                   and self._valid(self.observations[oid])
                   and not is_positive_topic_mismatch(self.observations[oid], slide)]
        for anchor in anchors:
            if (anchor.period != observation.period or anchor.period_basis != observation.period_basis
                    or anchor.entity != observation.entity
                    or anchor.category_dimensions != observation.category_dimensions
                    or (anchor.unit_family or anchor.unit, anchor.currency, anchor.unit_scale, anchor.raw_unit)
                       != (observation.unit_family or observation.unit, observation.currency,
                           observation.unit_scale, observation.raw_unit)):
                continue
            shared = {e.table_id for e in observation.evidence if e.table_id} & {
                e.table_id for e in anchor.evidence if e.table_id}
            if not shared:
                continue
            pages = {e.page for e in observation.evidence if e.table_id in shared} & {
                e.page for e in anchor.evidence if e.table_id in shared}
            for page_number in sorted(pages):
                page = self.pages.get(page_number)
                if page is None:
                    continue
                # A literal definition/reconciliation must name both measures;
                # sharing a table, or merely naming an expense, is insufficient.
                for sentence in re.split(r"(?<=[.!?])\s+", page.text):
                    if (_names(observation, sentence) and _names(anchor, sentence)
                            and not re.search(r"(?i)\b(?:not|never|unrelated|excluding|excludes?)\b", sentence)
                            and re.search(r"(?i)\b(?:reconcil\w*|adjusted\s+for|includes?|"
                                          r"consists?\s+of|comprises?|components?\s+of)\b", sentence)):
                        return SourceTopicRelation("source_definition", (observation.id, anchor.id),
                                                   (page_number,), sentence.strip())
                relation = self._adjacent_sum(observation, anchor, shared, page_number)
                if relation:
                    return relation
        return None

    def _adjacent_sum(self, item, subtotal, tables, page_number):
        # A source-ordered three-row subtotal can prove a relationship without
        # a financial taxonomy. Either preceding addend has the same support
        # relation, provided both signed values reconcile to the final row.
        if (item.row_id is None or subtotal.row_id is None or subtotal.row_id < 2
                or item.row_id not in (subtotal.row_id - 2, subtotal.row_id - 1)
                or item.column_id is None):
            return None
        if item.column_id != subtotal.column_id or not self._same_sum_scope(item, subtotal):
            return None
        table_id = item.effective_table_id
        if table_id not in tables or subtotal.effective_table_id != table_id:
            return None
        source_tables = [t for t in self.pages[page_number].tables if t.table_id == table_id]
        if len(source_tables) != 1:
            return None
        table = source_tables[0]
        if not self._source_cell(item, table, page_number) or not self._source_cell(subtotal, table, page_number):
            return None
        peer_row = subtotal.row_id - 1 if item.row_id == subtotal.row_id - 2 else subtotal.row_id - 2
        peers = [o for o in self.result.observations if self._valid(o)
                 and o.effective_table_id == table_id and o.row_id == peer_row
                 and o.column_id == item.column_id and self._same_sum_scope(o, item)]
        if len({o.value for o in peers}) != 1:
            return None
        if any(not self._source_cell(o, table, page_number) for o in peers):
            return None
        first, second = sorted((item, peers[0]), key=lambda o: o.row_id)
        tolerance = .15 if item.unit_family == "percentage" else max(1e-7, abs(subtotal.value) * 1e-6)
        if abs(first.value + second.value - subtotal.value) > tolerance:
            return None
        return SourceTopicRelation("source_adjacent_subtotal", (first.id, second.id, subtotal.id), (page_number,))

    @staticmethod
    def _same_sum_scope(first, second):
        fields = ("unit", "unit_family", "currency", "raw_unit", "unit_scale", "period", "period_basis",
                  "period_start", "period_end", "as_of_date", "entity", "category_dimensions",
                  "parent_section", "dimensions", "ifrs_status", "audited_status")
        return all(getattr(first, field) == getattr(second, field) for field in fields)

    @staticmethod
    def _source_cell(item, table, page_number):
        """Bind a signed observation to the resolved source row and cell."""
        from adaptive_document_agent.extraction.numeric_parser import parse_number

        if (item.row_id is None or item.column_id is None
                or not 0 <= item.row_id < len(table.rows)):
            return False
        row = table.rows[item.row_id]
        if (row.page != page_number or row.alignment_status != "resolved"
                or not 0 < item.column_id < len(row.cells) or not row.cells[0]):
            return False
        source_label = " ".join(row.cells[0].split()).casefold()
        if not any(e.page == page_number and e.table_id == table.table_id and e.row_label
                   and " ".join(e.row_label.split()).casefold() == source_label for e in item.evidence):
            return False
        cell = row.cells[item.column_id]
        if cell is None or " ".join(cell.split()) != " ".join(item.raw_value.split()):
            return False
        parsed = parse_number(cell)
        if parsed is None:
            return False
        # Raw cells without a scale suffix use the observation's retained
        # table scale. A literal suffix has already been applied by the parser.
        scale = item.unit_scale if parsed.scale == 1 and item.unit_scale is not None else 1
        expected = parsed.value * scale
        return (math.isfinite(expected)
                and math.isclose(expected, item.value, rel_tol=1e-9, abs_tol=1e-7))
