"""Provider diagnostic covering text and validated JSON."""

from pydantic import BaseModel

from .gateway import LLMGateway


class DiagnosticAnswer(BaseModel):
    status: str


def test_model(gateway: LLMGateway) -> dict[str, object]:
    text = gateway.generate_text([{"role": "user", "content": "Reply with exactly: ok"}], stage="discovery", max_tokens=10)
    structured = gateway.generate_structured(
        [{"role": "user", "content": 'Return JSON only: {"status":"ok"}'}],
        DiagnosticAnswer,
        stage="discovery",
    )
    return {
        "connected": bool(text.strip()),
        "text_response": text.strip()[:100],
        "json_valid": structured.status.casefold() == "ok",
        "vision": gateway.client.supports("vision"),
        "tool_calling": gateway.client.supports("tool_calling"),
    }

