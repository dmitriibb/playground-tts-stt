"""Model file downloads from the Hugging Face Hub or plain URLs, with progress reporting.

A finished download is marked with a `.download_complete` file, so a partial
download (crash, network error) is never mistaken for a usable model.
"""

from __future__ import annotations

import fnmatch
import logging
import shutil
import tempfile
import threading
import zipfile
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

log = logging.getLogger("common.downloads")

COMPLETE_MARKER = ".download_complete"


class HfFiles(BaseModel):
    repo: str
    revision: str | None = None
    patterns: list[str]  # allow_patterns for snapshot_download (exact paths work too)


class UrlFile(BaseModel):
    url: str
    filename: str
    extract: bool = False  # zip archive: extract into the model dir, dropping the top folder


class DownloadSource(BaseModel):
    hf: HfFiles | None = None
    urls: list[UrlFile] = []

    def describe(self) -> str:
        if self.hf:
            return f"hf://{self.hf.repo}" + (f"@{self.hf.revision}" if self.hf.revision else "")
        return ", ".join(u.url for u in self.urls)


ProgressFn = Callable[[float, float], None]  # (downloaded_mb, total_mb)


def is_downloaded(target: Path) -> bool:
    return (target / COMPLETE_MARKER).exists()


def dir_size_mb(path: Path) -> float:
    if not path.exists():
        return 0.0
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    return total / (1024 * 1024)


def delete_files(target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)


def download(source: DownloadSource, target: Path, progress: ProgressFn) -> None:
    """Blocking download (run it in a thread)."""
    target.mkdir(parents=True, exist_ok=True)
    (target / COMPLETE_MARKER).unlink(missing_ok=True)
    if source.hf:
        _download_hf(source.hf, target, progress)
    for item in source.urls:
        _download_url(item, target, progress)
    (target / COMPLETE_MARKER).write_text("ok", encoding="utf-8")


def _download_hf(spec: HfFiles, target: Path, progress: ProgressFn) -> None:
    from huggingface_hub import HfApi, snapshot_download

    total_mb = 0.0
    try:
        info = HfApi().model_info(spec.repo, revision=spec.revision, files_metadata=True)
        total_mb = sum(
            (s.size or 0) for s in info.siblings or []
            if any(fnmatch.fnmatch(s.rfilename, p) for p in spec.patterns)
        ) / (1024 * 1024)
    except Exception as exc:
        log.debug("Could not read file sizes for %s: %s", spec.repo, exc)

    stop = threading.Event()

    def poll() -> None:  # hf_hub_download has no byte callback: watch the directory grow
        while not stop.wait(0.5):
            progress(dir_size_mb(target), total_mb)

    watcher = threading.Thread(target=poll, daemon=True)
    watcher.start()
    try:
        snapshot_download(spec.repo, revision=spec.revision, local_dir=str(target),
                          allow_patterns=spec.patterns)
    finally:
        stop.set()
        watcher.join()
    shutil.rmtree(target / ".cache", ignore_errors=True)
    progress(dir_size_mb(target), total_mb or dir_size_mb(target))


def _download_url(item: UrlFile, target: Path, progress: ProgressFn) -> None:
    import httpx

    dest = target / item.filename
    part = dest.with_name(dest.name + ".part")
    done = 0
    with httpx.stream("GET", item.url, follow_redirects=True, timeout=60) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("content-length") or 0) / (1024 * 1024)
        with open(part, "wb") as fh:
            for chunk in resp.iter_bytes(1 << 20):
                fh.write(chunk)
                done += len(chunk)
                progress(done / (1024 * 1024), total)
    part.replace(dest)
    if item.extract:
        _extract_zip(dest, target)
        dest.unlink()


def _extract_zip(archive: Path, target: Path) -> None:
    with tempfile.TemporaryDirectory(dir=target) as tmp, zipfile.ZipFile(archive) as zf:
        root = Path(tmp).resolve()
        for member in zf.namelist():  # refuse path traversal
            if not (root / member).resolve().is_relative_to(root):
                raise ValueError(f"Unsafe path in archive: {member}")
        zf.extractall(root)
        entries = list(root.iterdir())
        src = entries[0] if len(entries) == 1 and entries[0].is_dir() else root
        for child in src.iterdir():
            shutil.move(str(child), str(target / child.name))
