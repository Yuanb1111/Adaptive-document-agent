"""Symmetric supporting roles require a selected, declared source subtotal."""

import pytest

from adaptive_document_agent.agent.presentation_topic_selector import series_directory
from adaptive_document_agent.document_model.topic_matcher import is_positive_topic_mismatch
from adaptive_document_agent.models import PresentationSlide
from adaptive_document_agent.validation.presentation_topic_relations import TopicRelationValidator
from tests.test_evidence_bound_topic_panels import relation_result


def _fixture():
    return relation_result(
        ["Revenue", "Cost of sales", "Gross profit"], [100, -63, 37],
        title="Gross profitability improvement",
        rationale="Compare gross profit with Revenue and Cost of sales.", unit="currency")


@pytest.mark.parametrize("index", [0, 1])
def test_either_signed_addend_is_supported_by_the_same_source_ordered_subtotal(index):
    result, slide = _fixture()
    item = result.observations[index]
    assert is_positive_topic_mismatch(item, slide)
    validator = TopicRelationValidator(result)
    relation = validator.relation(item, slide)
    assert relation.kind == "source_adjacent_subtotal"
    assert relation.observation_ids == tuple(o.id for o in result.observations)
    assert relation.source_pages == (234,)
    assert not validator.mismatch(item, slide)
    # The relation belongs to the authored slide scope, not a chart caption.
    caption = PresentationSlide(id="caption", slide_type="analysis", title="Gross profit margin")
    assert is_positive_topic_mismatch(item, caption)


@pytest.mark.parametrize("index", [0, 1])
def test_source_ordered_proof_also_works_with_nonfinancial_labels(index):
    result, slide = relation_result(
        ["Input energy", "Energy adjustment", "Available energy"], [100, -63, 37],
        title="Available energy", rationale="Compare Available energy, Input energy and Energy adjustment.",
        unit="kWh")
    relation = TopicRelationValidator(result).relation(result.observations[index], slide)
    assert relation.kind == "source_adjacent_subtotal"
    assert relation.observation_ids == tuple(o.id for o in result.observations)


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize("change", [
    "arithmetic", "unit", "currency", "scale", "period", "period_basis", "entity", "category",
    "parent", "dimension", "table", "alignment", "undeclared", "unselected", "row", "column",
    "source_label", "source_value", "source_page", "invalid", "anomaly",
])
def test_either_addend_keeps_all_source_scope_and_selection_guards(index, change):
    result, slide = _fixture()
    item = result.observations[index]
    table = result.document.pages[0].tables[0]
    if change == "arithmetic":
        item.value += 1
        item.raw_value = str(item.value)
        table.rows[index].cells[1] = item.raw_value
    elif change == "unit": item.unit = "count"
    elif change == "currency": item.currency = "USD"
    elif change == "scale": item.unit_scale = 1000
    elif change == "period": item.period = "6M2024"
    elif change == "period_basis": item.period_basis = "6M"
    elif change == "entity": item.entity = "Other entity"
    elif change == "category": item.category_dimensions = {"business": "Other segment"}
    elif change == "parent": item.parent_section = "Other source scope"
    elif change == "dimension": item.dimensions = {"scenario": "Other case"}
    elif change == "table":
        item.table_id = item.evidence[0].table_id = "other-table"
    elif change == "alignment": table.rows[index].alignment_status = "ambiguous"
    elif change == "undeclared": result.presentation_topics.topics[0].rationale = "Compare gross profit."
    elif change == "unselected":
        _, lookup = series_directory(result)
        result.presentation_topics.topics[0].series_ids = [
            sid for sid, items in lookup.items() if item.id not in {o.id for o in items}]
    elif change == "row": item.row_id = 4
    elif change == "column": item.column_id = 2
    elif change == "source_label": item.evidence[0].row_label = "Other source label"
    elif change == "source_value": table.rows[index].cells[1] = "999"
    elif change == "source_page": item.evidence[0].page = 235
    elif change == "invalid": item.validation_status = "ambiguous"
    else: item.anomaly_notes = ["Conflicting source cell"]
    assert TopicRelationValidator(result).relation(item, slide) is None
    assert TopicRelationValidator(result).mismatch(item, slide)


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize("change", ["arithmetic", "scope", "table", "alignment", "source_value", "source_label", "source_page", "conflicting_copy"])
def test_other_addend_must_have_the_same_unambiguous_source_proof(index, change):
    result, slide = _fixture()
    item, peer = result.observations[index], result.observations[1 - index]
    table = result.document.pages[0].tables[0]
    if change == "arithmetic":
        peer.value += 1
        peer.raw_value = str(peer.value)
        table.rows[peer.row_id].cells[1] = peer.raw_value
    elif change == "scope": peer.parent_section = "Different parent"
    elif change == "table": peer.table_id = peer.evidence[0].table_id = "other-table"
    elif change == "alignment": table.rows[peer.row_id].alignment_status = "ambiguous"
    elif change == "source_value": table.rows[peer.row_id].cells[1] = "999"
    elif change == "source_label": peer.evidence[0].row_label = "Different row"
    elif change == "source_page": peer.evidence[0].page = 235
    else:
        copy = peer.model_copy(deep=True)
        copy.id = "conflicting-copy"
        copy.value += 1
        result.observations.append(copy)
    assert TopicRelationValidator(result).relation(item, slide) is None


@pytest.mark.parametrize("index", [0, 1])
def test_raw_source_value_must_match_the_retained_normalized_scale(index):
    result, slide = _fixture()
    for item in result.observations:
        item.unit_scale = 1000
        item.raw_unit = "currency in thousands"
        item.value *= 1000
    assert TopicRelationValidator(result).relation(result.observations[index], slide)
    result.observations[index].value /= 1000
    assert TopicRelationValidator(result).relation(result.observations[index], slide) is None


def test_duplicate_source_table_identity_is_ambiguous():
    result, slide = _fixture()
    page = result.document.pages[0]
    page.tables.append(page.tables[0].model_copy(deep=True))
    assert TopicRelationValidator(result).relation(result.observations[0], slide) is None


def test_source_row_qualifiers_cannot_be_erased_when_binding_a_cell():
    result, slide = _fixture()
    item = result.observations[0]
    item.evidence[0].row_label = "Revenue (adjusted)"
    result.document.pages[0].tables[0].rows[0].cells[0] = "Revenue (unadjusted)"
    assert TopicRelationValidator(result).relation(item, slide) is None


def test_table_support_does_not_relax_a_first_addends_own_chart_caption():
    from adaptive_document_agent.models import ChartPlan
    from adaptive_document_agent.services.qa_reporter import run_comprehensive_qa

    result, slide = _fixture()
    chart = ChartPlan(id="wrong-caption", title="Gross profit margin", question="How did gross margin change?",
                      chart_type="bar", observation_ids=[result.observations[0].id], source_pages=[234])
    result.charts = [chart]
    slide.chart_ids = [chart.id]
    result.presentation_plan.slides[3] = slide
    assert not TopicRelationValidator(result).mismatch(result.observations[0], slide)
    qa = run_comprehensive_qa(result, auto_repair=False)
    assert any(issue.code == "chart_title_data_mismatch" for issue in qa.critical_errors)
