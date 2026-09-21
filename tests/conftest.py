import pytest


@pytest.fixture
def local_render_stub(monkeypatch):
    """Explicit opt-in for OOXML unit tests; does not bypass the visual gate."""
    from tests.ppt_render_stub import LocalRenderStub
    from adaptive_document_agent.services import presentation_visual_qa
    renderer = LocalRenderStub()
    monkeypatch.setattr(presentation_visual_qa, "configured_renderer", lambda: renderer)
    return renderer
