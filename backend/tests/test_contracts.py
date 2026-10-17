"""Module boundaries (needed for the future 3-service split) are enforced by import-linter."""

import shutil
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def test_import_contracts():
    exe = shutil.which("lint-imports") or str(Path(sys.executable).parent / "lint-imports")
    result = subprocess.run([exe], cwd=BACKEND, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_catalogs_are_consistent():
    from stt.catalog import catalog as stt_catalog
    from stt.schemas import STT_MODES
    from tts.catalog import catalog as tts_catalog

    ids = [s.id for s in [*stt_catalog(), *tts_catalog()]]
    assert len(ids) == len(set(ids))
    for spec in stt_catalog():
        assert set(spec.modes) <= set(STT_MODES)
        if spec.native_batching:
            assert spec.modes["file_batch"]
    for spec in tts_catalog():
        assert spec.streaming_kind in ("model_streaming", "segment_streaming", "output_chunked")
