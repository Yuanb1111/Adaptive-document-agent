"""Independent report downloads: a failed format must not hide other exports or QA."""

import logging
from typing import Any

from adaptive_document_agent.models import PipelineResult
from adaptive_document_agent.services.export import export_csv, export_markdown, export_pdf


def render_report_downloads(st: Any, result: PipelineResult, columns: tuple[Any, ...]) -> None:
    formats = (
        ("Markdown", "Download Markdown", export_markdown, "analysis_report.md", "text/markdown"),
        ("PDF", "Download report (.pdf)", export_pdf, "analysis_report.pdf", "application/pdf"),
        ("CSV", "Download CSV", export_csv, "extracted_observations.csv", "text/csv"),
    )
    for column, (kind, label, exporter, filename, mime) in zip(columns, formats):
        with column:
            try:
                payload = exporter(result)
            except Exception as exc:
                # Exceptions may contain source text, credentials or private paths.
                error_type = type(exc).__name__
                logging.getLogger(__name__).warning("%s export failed (%s)", kind, error_type)
                st.button(label, disabled=True, use_container_width=True)
                st.warning(f"{kind} export is unavailable ({error_type}). Other downloads and PowerPoint QA are unaffected.")
            else:
                st.download_button(label, payload, filename, mime, use_container_width=True)
