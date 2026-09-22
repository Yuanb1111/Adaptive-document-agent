"""Build and locally render a labelled synthetic regression deck.

Run with development dependencies installed. This is not an analysis of a PDF
and never calls a model. Optional artwork is a user-selected local PNG/JPEG.
"""

import argparse
import json
from pathlib import Path

from adaptive_document_agent.services.export import export_pptx_with_report
from adaptive_document_agent.services.presentation_rendering import configured_renderer
from tests.test_p1_theme_planning import themed_result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artwork", type=Path)
    parser.add_argument("--layout", choices=["kpi_band", "two_up", "three_up", "hero_plus_supporting", "chart_plus_commentary"], default="kpi_band")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    result = themed_result()
    result.presentation_plan.title = "Layout regression preview"
    result.presentation_plan.planning_origin = "model"
    result.presentation_plan.slides[0].title = "Layout regression preview"
    result.presentation_plan.slides[0].message = "Synthetic test data. This preview demonstrates layout only."
    result.profile.document_type = "Synthetic layout fixture"
    result.profile.document_purpose = "Check editable charts and supported commentary using synthetic test data."
    result.presentation_plan.company.name = "Synthetic example"
    result.presentation_plan.company.one_line_description = "A fictional operating activity dataset for layout testing."
    result.presentation_plan.company.source_pages = [3]
    result.presentation_plan.company.products = ["Example product", "Example service"]
    result.presentation_plan.company.business_model = "Fictional operating activity for visual regression testing."
    result.presentation_plan.company.document_type = "Synthetic layout fixture"
    slide = result.presentation_plan.slides[3]
    slide.layout = args.layout
    slide.visual_blocks[-1].observation_ids = ["a2", "b2"]
    if args.layout == "three_up":
        from adaptive_document_agent.models import PresentationVisualBlock
        extra = [o.model_copy(update={"id": "c" + str(i), "metric_original": "Units inspected"})
                 for i, o in enumerate(result.observations[:3])]
        result.observations.extend(extra)
        result.charts.append(result.charts[0].model_copy(update={"id": "c", "title": "Units inspected", "observation_ids": [o.id for o in extra]}))
        slide.chart_ids.append("c")
        slide.visual_blocks.insert(2, PresentationVisualBlock(role="supporting", chart_ids=["c"]))
        result.presentation_plan.themes[0].chart_ids.append("c")
    if args.layout == "chart_plus_commentary":
        slide.chart_ids = ["a"]
        slide.visual_blocks = slide.visual_blocks[:1]
    renderer = configured_renderer()
    verified = export_pptx_with_report(result, renderer=renderer, artwork=args.artwork.read_bytes() if args.artwork else None)
    (args.output / "layout-preview.pptx").write_bytes(verified.payload)
    (args.output / "visual-qa.json").write_text(json.dumps(verified.report.to_dict(), indent=2), encoding="utf-8")
    render_dir = args.output / "slides"
    render_dir.mkdir()
    pages = renderer.render(verified.payload, render_dir)
    print(json.dumps({"slides": len(pages), "qa": verified.report.status, "output": str(args.output.resolve())}))


if __name__ == "__main__":
    main()
