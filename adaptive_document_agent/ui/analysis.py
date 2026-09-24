"""Analysis report tab."""

import re

from adaptive_document_agent.models import PipelineResult


def split_markdown_sections(markdown: str) -> tuple[str, list[tuple[str, str]]]:
    """Split a report at level-two headings while preserving source order."""
    matches = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", markdown))
    if not matches:
        return markdown.strip(), []
    intro = markdown[: matches[0].start()].strip()
    sections = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        sections.append((match.group(1).strip(), markdown[match.end() : end].strip()))
    return intro, sections


def render(st, result: PipelineResult) -> None:
    intro, sections = split_markdown_sections(result.report_markdown)
    if intro:
        st.markdown(intro)
    if not sections:
        return
    st.caption(f"Report sections: {len(sections)}. Open only the sections you want to inspect.")
    for index, (title, body) in enumerate(sections):
        with st.expander(f"{index + 1}. {title}", expanded=index == 0):
            st.markdown(body or "No additional content.")
