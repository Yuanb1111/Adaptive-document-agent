"""Local, explicitly configured rendering boundary. No network or model fallback."""

from dataclasses import dataclass
import io
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
import time
import zipfile

from lxml import etree


class RenderingError(RuntimeError):
    pass


@dataclass(frozen=True)
class RenderedPage:
    png: bytes
    layout: dict


def check_render_input(payload: bytes, *, _depth: int = 0) -> None:
    """Reject active/external resources before invoking a local rendering engine.

    Static hyperlinks are not fetched by our adapter. Linked media, OLE and macros
    are disallowed, including external links inside embedded chart workbooks.
    """
    if _depth > 1:
        raise RenderingError("Nested embedded packages are not supported for rendering.")
    if len(payload) > 100_000_000:
        raise RenderingError("Presentation exceeds the 100 MB rendering limit.")
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            entries = archive.infolist()
            if len(entries) > 10000 or sum(e.file_size for e in entries) > 250_000_000:
                raise RenderingError("Presentation exceeds the unpacked rendering limit.")
            if len({e.filename for e in entries}) != len(entries):
                raise RenderingError("Duplicate package parts are not supported for rendering.")
            for entry in entries:
                name = entry.filename.lower()
                if "vbaproject" in name or "oleobject" in name or name.startswith("xl/externallinks/"):
                    raise RenderingError("Active presentation content is not supported for rendering.")
                if name.endswith((".xml", ".rels", ".svg")) and b"<!DOCTYPE" in archive.read(entry).upper():
                    raise RenderingError("Document type declarations are not allowed in presentation resources.")
                if name.endswith(".rels"):
                    root = etree.fromstring(archive.read(entry), parser=etree.XMLParser(resolve_entities=False, no_network=True))
                    for rel in root:
                        if rel.get("TargetMode", "").lower() == "external" and not rel.get("Type", "").endswith("/hyperlink"):
                            raise RenderingError("External presentation resources are not allowed for local rendering.")
                if name.startswith("ppt/embeddings/"):
                    if not name.endswith(".xlsx"):
                        raise RenderingError("Only embedded, non-macro chart workbooks are supported.")
                    check_render_input(archive.read(entry), _depth=_depth+1)
    except (zipfile.BadZipFile, etree.XMLSyntaxError) as exc:
        raise RenderingError("Invalid presentation package.") from exc


class ArtifactRenderer:
    """Render using an administrator-configured local Node/Artifact Tool runtime.

    The static helper never evaluates slide text as code. Diagnostics stay in a
    private temporary directory owned by the caller; stderr is not exposed.
    """

    def __init__(self, node: str, module: str, *, timeout: float = 120):
        self.node = Path(node)
        self.module = Path(module)
        self.timeout = timeout
        if (not self.node.is_absolute() or not self.module.is_absolute()
                or not self.node.is_file() or not self.module.is_file()
                or str(node).startswith(("\\\\", "//")) or str(module).startswith(("\\\\", "//"))):
            raise RenderingError("Configure absolute local PPTX_QA_NODE and PPTX_QA_ARTIFACT_MODULE paths.")

    @property
    def identity(self) -> str:
        # Runtime/helper changes invalidate a caller's session-local cache.
        paths = (self.node, self.module, Path(__file__).with_name("render_presentation.mjs"))
        return "artifact-local-v1:" + ":".join(f"{p}:{p.stat().st_size}:{p.stat().st_mtime_ns}" for p in paths) + ":fonts=" + os.environ.get("PPTX_QA_FONT_REVISION", "default")

    def render(self, payload: bytes, directory: Path) -> list[RenderedPage]:
        check_render_input(payload)
        source = directory / "candidate.pptx"
        if (directory / "complete.json").exists():
            raise RenderingError("Rendering requires a fresh output directory.")
        source.write_bytes(payload)
        helper = Path(__file__).with_name("render_presentation.mjs")
        try:
            process = subprocess.Popen(
                [str(self.node), str(helper), str(self.module), str(source), str(directory)],
                shell=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except OSError as exc:
            raise RenderingError("Local presentation renderer could not start.") from exc
        deadline = time.monotonic() + self.timeout
        try:
            while not (directory / "complete.json").is_file():
                if process.poll() is not None:
                    raise RenderingError("Local presentation renderer failed before completing all pages.")
                if time.monotonic() >= deadline:
                    raise RenderingError("Local presentation rendering timed out.")
                time.sleep(.05)
        finally:
            # Only terminate the worker we created. Never search for or kill
            # unrelated Node/Office processes. All output writes precede receipt.
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
        try:
            manifest = json.loads((directory / "complete.json").read_text(encoding="utf-8"))
            count = manifest["pages"]
            if (type(count) is not int or not 1 <= count <= 150 or manifest.get("complete") is not True
                    or manifest.get("inputSha256") != hashlib.sha256(payload).hexdigest()):
                raise ValueError("invalid manifest")
            outputs = [directory / f"slide-{i}.{suffix}" for i in range(1, count+1) for suffix in ("png", "json")]
            if sum(p.stat().st_size for p in outputs) > 300_000_000:
                raise RenderingError("Rendered output exceeds the 300 MB validation limit.")
            return [RenderedPage((directory / f"slide-{i}.png").read_bytes(),
                                 json.loads((directory / f"slide-{i}.json").read_text(encoding="utf-8")))
                    for i in range(1, count + 1)]
        except (OSError, ValueError, KeyError) as exc:
            raise RenderingError("Local renderer did not produce a complete page set.") from exc


def configured_renderer():
    backend = os.environ.get("PPTX_QA_BACKEND", "auto").strip().lower()
    if backend not in {"auto", "artifact", "libreoffice"}:
        raise RenderingError("PPTX_QA_BACKEND must be auto, artifact, or libreoffice.")
    node = os.environ.get("PPTX_QA_NODE", "")
    module = os.environ.get("PPTX_QA_ARTIFACT_MODULE", "")
    if backend == "artifact" or (backend == "auto" and (node or module)):
        # An explicit but invalid administrator configuration is an error, not
        # permission to silently switch rendering engines.
        if not node or not module:
            raise RenderingError("Configure both PPTX_QA_NODE and PPTX_QA_ARTIFACT_MODULE for Artifact rendering; no cloud fallback is used.")
        return ArtifactRenderer(node, module)
    executable = os.environ.get("PPTX_QA_LIBREOFFICE", "") or shutil.which("libreoffice") or shutil.which("soffice")
    if executable:
        from .libreoffice_rendering import LibreOfficeRenderer
        return LibreOfficeRenderer(executable)
    raise RenderingError("Verified PowerPoint export requires a server-local renderer. On Streamlit Cloud deploy the repository packages.txt (LibreOffice and fonts), then reboot the app. Alternatively configure PPTX_QA_NODE and PPTX_QA_ARTIFACT_MODULE; no cloud fallback is used.")
