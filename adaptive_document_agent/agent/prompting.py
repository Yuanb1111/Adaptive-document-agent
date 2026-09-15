"""Prompt construction with explicit untrusted-document boundaries."""

from pathlib import Path

PROMPT_ROOT = Path(__file__).resolve().parent.parent / "prompts"


def load_prompt(name: str) -> str:
    return (PROMPT_ROOT / name).read_text(encoding="utf-8")


def untrusted_document_message(content: str) -> dict[str, str]:
    return {
        "role": "user",
        "content": "<UNTRUSTED_DOCUMENT_CONTENT>\n" + content + "\n</UNTRUSTED_DOCUMENT_CONTENT>",
    }

