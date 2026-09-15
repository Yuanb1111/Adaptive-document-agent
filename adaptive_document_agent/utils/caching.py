"""Local, content-addressed JSON cache with atomic replacement."""

import json
import os
import tempfile
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class DiskCache:
    def __init__(self, root: str | Path = ".adaptive_document_cache") -> None:
        self.root = Path(root)

    def get_model(self, key: str, model: type[T]) -> T | None:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            return model.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def set_model(self, key: str, value: BaseModel) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        target = self._path(key)
        handle, temporary_name = tempfile.mkstemp(prefix="cache-", suffix=".tmp", dir=self.root)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(value.model_dump(mode="json"), stream, ensure_ascii=False)
            os.replace(temporary_name, target)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    def _path(self, key: str) -> Path:
        safe = "".join(character for character in key if character.isalnum() or character in "-_")
        return self.root / f"{safe}.json"

