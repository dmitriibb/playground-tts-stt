"""Built-in audio clips: fixtures/audio/<lang>/<name>.wav with an optional <name>.txt reference."""

from __future__ import annotations

import wave
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel

from common.errors import AppError, ErrorCode
from gateway.deps import services

router = APIRouter(prefix="/api/fixtures", tags=["fixtures"])

_AUDIO_EXT = {".wav", ".mp3", ".ogg", ".flac", ".webm", ".m4a"}


class Fixture(BaseModel):
    id: str
    language: str
    name: str
    duration_ms: float | None = None
    reference_text: str | None = None


def _duration(path: Path) -> float | None:
    if path.suffix != ".wav":
        return None
    try:
        with wave.open(str(path), "rb") as wf:
            return round(wf.getnframes() * 1000 / wf.getframerate(), 1)
    except Exception:
        return None


@router.get("", response_model=list[Fixture])
async def list_fixtures(svc=Depends(services)) -> list[Fixture]:
    root: Path = svc.settings.fixtures_dir.resolve()
    if not root.exists():
        return []
    out = []
    for path in sorted(root.glob("*/*")):
        if path.suffix.lower() not in _AUDIO_EXT:
            continue
        ref = path.with_suffix(".txt")
        out.append(Fixture(
            id=f"{path.parent.name}/{path.name}", language=path.parent.name, name=path.stem,
            duration_ms=_duration(path),
            reference_text=ref.read_text(encoding="utf-8").strip() if ref.exists() else None,
        ))
    return out


@router.get("/{language}/{name}")
async def get_fixture(language: str, name: str, svc=Depends(services)) -> FileResponse:
    root: Path = svc.settings.fixtures_dir.resolve()
    path = (root / language / name).resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.suffix.lower() not in _AUDIO_EXT:
        raise AppError(ErrorCode.INVALID_REQUEST, f"No fixture {language}/{name}")
    return FileResponse(path)
