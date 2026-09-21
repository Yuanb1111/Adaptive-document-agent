"""Independent report downloads: a failed format must not hide other exports or QA."""

import logging
from hashlib import sha256
from typing import Any

from adaptive_document_agent.models import PipelineResult
from adaptive_document_agent.services.export import export_csv, export_markdown, export_pdf


def render_report_downloads(st: Any, result: PipelineResult, columns: tuple[Any, ...], *, pdf_cache: dict | None = None) -> None:
    formats = (
        ("Markdown", "Download Markdown", export_markdown, "analysis_report.md", "text/markdown"),
        ("PDF", "Download report (.pdf)", export_pdf, "analysis_report.pdf", "application/pdf"),
        ("CSV", "Download CSV", export_csv, "extracted_observations.csv", "text/csv"),
    )
    for column, (kind, label, exporter, filename, mime) in zip(columns, formats):
        with column:
            pdf_key = None
            if kind == "PDF" and pdf_cache is not None:
                # PDF uses only Markdown and report title. One session-owned
                # entry; editing the report cannot serve a stale download.
                pdf_key = sha256((result.report_plan.title + "\0" + result.report_markdown).encode()).hexdigest()
                if pdf_key not in pdf_cache:
                    pdf_cache.clear()
                    if not st.button("Generate PDF report", key="generate_pdf_report", use_container_width=True):
                        st.caption("Optional: generated only when requested, so PPT need not wait for PDF.")
                        continue
            try:
                payload = pdf_cache[pdf_key] if pdf_key is not None and pdf_key in pdf_cache else exporter(result)
                if pdf_key is not None:
                    pdf_cache[pdf_key] = payload
            except Exception as exc:
                # Exceptions may contain source text, credentials or private paths.
                error_type = type(exc).__name__
                logging.getLogger(__name__).warning("%s export failed (%s)", kind, error_type)
                st.button(label, disabled=True, use_container_width=True)
                st.warning(f"{kind} export is unavailable ({error_type}). Other downloads and PowerPoint QA are unaffected.")
            else:
                st.download_button(label, payload, filename, mime, use_container_width=True)
