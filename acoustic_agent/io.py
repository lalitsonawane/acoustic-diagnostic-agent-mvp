"""Audio loading, the bundled sample library and export helpers."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from acoustic_agent.synth import Signal

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = REPO_ROOT / "data" / "samples"
MANIFEST_PATH = SAMPLES_DIR / "manifest.csv"

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_DURATION_S = 120.0


class AudioLoadError(ValueError):
    """Raised when an upload cannot be decoded or violates size limits."""


def load_audio(source: bytes | str | Path | io.BufferedIOBase, name: str = "upload") -> Signal:
    """Decode a WAV/FLAC/OGG file to a mono float32 :class:`Signal`.

    Multi-channel files are averaged to mono. Enforces size and duration limits so a
    hostile or accidental upload cannot exhaust memory.
    """
    if isinstance(source, (str, Path)):
        path = Path(source)
        if path.stat().st_size > MAX_UPLOAD_BYTES:
            raise AudioLoadError(f"{path.name} exceeds the {MAX_UPLOAD_BYTES // 2**20} MB upload limit")
        handle: Any = str(path)
        name = path.name
    elif isinstance(source, (bytes, bytearray)):
        if len(source) > MAX_UPLOAD_BYTES:
            raise AudioLoadError(f"{name} exceeds the {MAX_UPLOAD_BYTES // 2**20} MB upload limit")
        handle = io.BytesIO(source)
    else:
        handle = source

    try:
        data, sr = sf.read(handle, dtype="float32", always_2d=True)
    except Exception as exc:  # soundfile raises RuntimeError/ValueError for bad input
        raise AudioLoadError(f"Could not decode {name}: {exc}") from exc

    if data.shape[0] == 0 or sr <= 0:
        raise AudioLoadError(f"{name} contains no audio samples")
    if data.shape[0] / sr > MAX_DURATION_S:
        raise AudioLoadError(f"{name} is longer than the {MAX_DURATION_S:.0f} s limit")

    mono = data.mean(axis=1).astype(np.float32) if data.shape[1] > 1 else data[:, 0]
    return Signal(audio=np.ascontiguousarray(mono), sample_rate_hz=int(sr), source=f"file:{name}")


def audio_to_wav_bytes(signal: Signal) -> bytes:
    buffer = io.BytesIO()
    sf.write(buffer, signal.audio, signal.sample_rate_hz, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


@dataclass(frozen=True)
class SampleEntry:
    file: str
    machine_profile: str
    condition: str
    fault_type: str
    sample_rate_hz: int
    channels: int
    purpose: str
    extra: str

    @property
    def path(self) -> Path:
        return SAMPLES_DIR / self.file

    @property
    def label(self) -> int | None:
        """Binary ground truth: 1 = fault, 0 = healthy, None = unlabelled edge case."""
        if self.condition == "fault":
            return 1
        if self.condition == "healthy":
            return 0
        return None


def load_sample_manifest(path: Path = MANIFEST_PATH) -> list[SampleEntry]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    entries: list[SampleEntry] = []
    for row in rows:
        entries.append(
            SampleEntry(
                file=row["file"],
                machine_profile=row.get("machine_profile", ""),
                condition=row.get("condition", ""),
                fault_type=row.get("fault_type", ""),
                sample_rate_hz=int(float(row.get("sample_rate_hz", 0) or 0)),
                channels=int(float(row.get("channels", 1) or 1)),
                purpose=row.get("purpose", ""),
                extra=row.get("extra", ""),
            )
        )
    return entries


def labels_from_manifest_text(text: str) -> dict[str, int | None]:
    """Parse a user manifest with ``file`` and ``condition`` (or ``label``) columns."""
    reader = csv.DictReader(io.StringIO(text))
    labels: dict[str, int | None] = {}
    for row in reader:
        name = (row.get("file") or row.get("filename") or "").strip()
        if not name:
            continue
        raw = (row.get("label") or row.get("condition") or "").strip().lower()
        if raw in {"1", "fault", "faulty", "anomaly", "true"}:
            labels[name] = 1
        elif raw in {"0", "healthy", "normal", "ok", "false"}:
            labels[name] = 0
        else:
            labels[name] = None
    return labels


def result_npz_bytes(signal: Signal, extras: dict[str, Any]) -> bytes:
    """Bundle the waveform and analysis metadata into an ``.npz`` for offline study."""
    buffer = io.BytesIO()
    np.savez_compressed(
        buffer,
        audio=signal.audio,
        sample_rate_hz=np.int64(signal.sample_rate_hz),
        metadata_json=np.bytes_(json.dumps(extras, default=str).encode("utf-8")),
    )
    return buffer.getvalue()


def rows_to_csv(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    keys: list[str] = []
    for row in rows:
        for k in row:
            if k not in keys:
                keys.append(k)
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=keys, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()
