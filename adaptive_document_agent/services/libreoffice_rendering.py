"""Deployable Linux-local PPT rendering, with isolated profiles and no network."""

import os
from pathlib import Path
import signal
import subprocess
import sys

from .presentation_rendering import RenderingError, check_render_input


class LibreOfficeRenderer:
    coverage = (
        "Every slide is rendered by server-local LibreOffice to PDF and PNG; no remote rendering service",
        "Object IDs/bounds come from source OOXML, not LibreOffice object metadata",
        "Visible slide text is checked against PDF text in the corresponding region",
        "Chart/table presence is checked through rendered region pixels, not recovered native object IDs",
        "Layout/source collisions use OOXML bounds; exact glyph clipping and PowerPoint parity are not certified",
    )

    def __init__(self, executable: str, *, timeout: float = 120):
        self.executable = Path(executable)
        self.timeout = timeout
        if sys.platform != "linux":
            raise RenderingError("The offline LibreOffice backend requires Linux. Use the configured Artifact backend on other platforms.")
        if not self.executable.is_absolute() or not self.executable.is_file() or not os.access(self.executable, os.X_OK):
            raise RenderingError("Install LibreOffice Impress from packages.txt or configure PPTX_QA_LIBREOFFICE with an executable absolute local path.")

    @property
    def identity(self):
        paths = [self.executable.resolve(), Path(__file__), Path(__file__).with_name("offline_render_worker.py"),
                 Path(__file__).with_name("pdf_render_layout.py")]
        # The launcher itself may be unchanged when the actual office binary is
        # upgraded. Include that binary too on Debian-family installations.
        binary = self.executable.resolve().with_name("soffice.bin")
        if binary.is_file():
            paths.append(binary)
        return "libreoffice-offline-v1:" + ":".join(f"{p}:{p.stat().st_size}:{p.stat().st_mtime_ns}" for p in paths) + ":fonts=" + os.getenv("PPTX_QA_FONT_REVISION", "default")

    def _run(self, arguments: list[str], directory: Path, *, timeout=None) -> None:
        worker = Path(__file__).with_name("offline_render_worker.py")
        # Do not inherit API keys, proxy credentials, or an existing LO profile.
        environment = {"PATH": os.defpath, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
                       "HOME": str(directory), "TMPDIR": str(directory), "SAL_USE_VCLPLUGIN": "svp"}
        process = None
        try:
            process = subprocess.Popen([sys.executable, str(worker), *arguments], shell=False,
                cwd=directory, env=environment, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            code = process.wait(timeout=timeout or self.timeout)
            if code == 78:
                raise RenderingError("Offline renderer isolation could not start. Install libseccomp2 and permit seccomp filtering; no cloud fallback is used.")
            if code != 0:
                raise RenderingError("LibreOffice failed to render the presentation; no unverified PPT is exported.")
        except subprocess.TimeoutExpired as exc:
            raise RenderingError("Local LibreOffice rendering timed out.") from exc
        except OSError as exc:
            raise RenderingError("Local LibreOffice renderer could not start.") from exc
        finally:
            if process is not None:
                # This group was created by us, includes office child processes,
                # and is never shared with other sessions or desktop programs.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)

    def render(self, payload: bytes, directory: Path):
        check_render_input(payload)
        directory = directory.resolve()
        source, target, profile = directory / "candidate.pptx", directory / "candidate.pdf", directory / "profile"
        if source.exists() or target.exists() or profile.exists():
            raise RenderingError("Rendering requires a fresh output directory.")
        source.write_bytes(payload)
        profile_user = profile / "user"
        profile_user.mkdir(parents=True)
        (profile_user / "registrymodifications.xcu").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<oor:items xmlns:oor="http://openoffice.org/2001/registry">'
            '<item oor:path="/org.openoffice.Office.Common/Security/Scripting">'
            '<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop>'
            '</item></oor:items>', encoding="utf-8")
        self._run([str(self.executable), f"-env:UserInstallation={profile.as_uri()}",
            "--headless", "--nologo", "--nodefault", "--norestore", "--convert-to", "pdf:impress_pdf_Export",
            "--outdir", str(directory), str(source)], directory)
        if not target.is_file() or not 0 < target.stat().st_size <= 100_000_000:
            raise RenderingError("LibreOffice did not produce a valid-sized PDF.")
        from .pdf_render_layout import pdf_rendered_pages
        return pdf_rendered_pages(payload, target)
