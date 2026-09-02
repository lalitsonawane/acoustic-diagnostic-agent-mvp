from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np
import pytest

from acoustic_agent.config import ExperimentConfig
from acoustic_agent.detect import Baseline
from acoustic_agent.io import (
    AudioLoadError,
    audio_to_wav_bytes,
    labels_from_manifest_text,
    load_audio,
    load_sample_manifest,
    result_npz_bytes,
    rows_to_csv,
)
from acoustic_agent.metrics import classification_report, pr_curve, roc_curve
from acoustic_agent.pipeline import analyze, analyze_synthetic, run_batch, sweep
from acoustic_agent.synth import Signal, synthesize

# --- metrics ------------------------------------------------------------------------------


def test_roc_perfect_and_random():
    labels = np.array([0, 0, 1, 1])
    assert roc_curve(labels, np.array([0.1, 0.2, 0.8, 0.9])).auc == pytest.approx(1.0)
    assert roc_curve(labels, np.array([0.9, 0.8, 0.2, 0.1])).auc == pytest.approx(0.0)
    assert roc_curve(labels, np.array([0.5, 0.5, 0.5, 0.5])).auc == pytest.approx(0.5)


def test_pr_curve_perfect():
    c = pr_curve(np.array([0, 0, 1, 1]), np.array([0.1, 0.2, 0.8, 0.9]))
    assert c.auc == pytest.approx(1.0, abs=1e-6)


def test_classification_report_counts():
    r = classification_report(np.array([0, 0, 1, 1, 1]), np.array([10, 90, 90, 90, 10]), threshold=50)
    assert (r.tp, r.fp, r.tn, r.fn) == (2, 1, 1, 1)
    assert r.precision == pytest.approx(2 / 3)
    assert r.recall == pytest.approx(2 / 3)
    assert r.accuracy == pytest.approx(3 / 5)
    assert r.specificity == pytest.approx(0.5)
    assert 0 < r.f1 < 1


def test_metrics_single_class_is_nan_not_error():
    c = roc_curve(np.array([1, 1]), np.array([0.1, 0.9]))
    assert np.isnan(c.auc)


# --- pipeline -----------------------------------------------------------------------------


def test_analyze_synthetic_end_to_end(config: ExperimentConfig, baseline: Baseline):
    res = analyze_synthetic(config.with_updates(inject_bursts=True), baseline)
    assert res.state == "CRITICAL"
    assert res.decision.actionable
    assert res.baseline is baseline
    assert res.steps[0][0] == "Signal received"
    assert res.steps[-1][0] == "Decision: CRITICAL"
    assert res.steps[-1][1] >= res.steps[0][1]
    row = res.summary_row({"label": 1})
    assert row["label"] == 1 and row["state"] == "CRITICAL"
    assert "feat_band_contrast_db" in row and "z_band_contrast_db" in row
    json.dumps(res.to_dict())  # must be serialisable


def test_analyze_calibrates_when_no_baseline(config: ExperimentConfig):
    res = analyze(synthesize(config), config)
    assert res.baseline.n == config.baseline_seeds
    assert res.state == "HEALTHY"


def test_run_batch_on_shipped_samples(samples_dir: Path, config: ExperimentConfig, baseline: Baseline):
    entries = load_sample_manifest()
    assert entries, "manifest should list the sample set"
    signals = [(load_audio(e.path), e.label) for e in entries if e.path.exists()]
    assert len(signals) == len(entries)
    batch = run_batch(signals, config, baseline)
    assert len(batch.rows) == len(signals)
    assert batch.report is not None
    # Edge cases (unlabelled or invalid) are skipped from the metrics, not from the rows.
    assert set(batch.skipped) >= {s.source for s, lbl in signals if lbl is None}
    # Perfect ranking: every fault scores above every healthy file.
    assert batch.report.roc is not None and batch.report.roc.auc == pytest.approx(1.0)
    assert batch.report.fp == 0, [r for r in batch.rows if r["label"] == 0 and r["state"] != "HEALTHY"]
    by_source = {r["source"]: r for r in batch.rows}
    # The deliberately weak sample sits near the floor and is allowed to land on WARNING;
    # everything else labelled fault must be CRITICAL, including the heavy-noise file.
    for name, row in by_source.items():
        if row["label"] == 1 and "weak" not in name:
            assert row["state"] == "CRITICAL", (name, row["score"], row["driver"])
    assert by_source["file:robotic_arm_fault_weak_48k.wav"]["state"] in {"WARNING", "CRITICAL"}
    assert by_source["file:robotic_arm_fault_noisy_48k.wav"]["driver"] == "band_contrast_transient_db"
    assert by_source["file:bearing_outer_race_fault_48k.wav"]["driver"] in {
        "residual_kurtosis",
        "envelope_peak_snr_db",
        "residual_crest_factor",
    }
    assert by_source["file:robotic_arm_fault_16k.wav"]["state"] == "CRITICAL (unconfirmed)"
    assert by_source["file:silence_48k.wav"]["state"] == "INVALID"
    assert "clipping" in by_source["file:robotic_arm_fault_clipped_48k.wav"]["flags"]


def test_sweep_recalibrates_and_separates(config: ExperimentConfig):
    pts = sweep(config.with_updates(duration_s=0.5, baseline_seeds=3), "noise_std", [0.01, 0.05], seeds=2)
    assert [p.value for p in pts] == [0.01, 0.05]
    for p in pts:
        row = p.row()
        assert row["fault_mean"] > row["healthy_mean"]
        assert len(p.fault_scores) == 2


def test_sweep_rejects_unknown_parameter(config: ExperimentConfig):
    with pytest.raises(ValueError):
        sweep(config, "nope", [1.0])


# --- io -----------------------------------------------------------------------------------


def test_wav_roundtrip(config: ExperimentConfig):
    sig = synthesize(config.with_updates(duration_s=0.2))
    back = load_audio(audio_to_wav_bytes(sig), name="x.wav")
    assert back.sample_rate_hz == sig.sample_rate_hz
    assert back.audio.shape == sig.audio.shape
    assert np.max(np.abs(back.audio - sig.audio)) < 1e-3  # 16-bit quantisation
    assert back.source == "file:x.wav"


def test_stereo_downmixed_to_mono(tmp_path: Path):
    import soundfile as sf

    stereo = np.stack([np.ones(1000), -np.ones(1000)], axis=1).astype(np.float32)
    p = tmp_path / "s.wav"
    sf.write(p, stereo, 8_000)
    sig = load_audio(p)
    assert sig.audio.shape == (1000,)
    assert np.allclose(sig.audio, 0.0, atol=1e-3)


def test_load_audio_rejects_garbage_and_oversize(tmp_path: Path):
    with pytest.raises(AudioLoadError, match="Could not decode"):
        load_audio(b"not a wav file", name="bad.wav")
    from acoustic_agent import io as aio

    with pytest.raises(AudioLoadError, match="upload limit"):
        load_audio(b"\0" * (aio.MAX_UPLOAD_BYTES + 1), name="huge.wav")


def test_manifest_labels_parser():
    text = "file,condition\na.wav,healthy\nb.wav,fault\nc.wav,edge_case\n"
    assert labels_from_manifest_text(text) == {"a.wav": 0, "b.wav": 1, "c.wav": None}
    assert labels_from_manifest_text("file,label\nx.wav,1\n") == {"x.wav": 1}


def test_npz_bundle_and_csv():
    sig = Signal(np.zeros(10, dtype=np.float32), 1000, "t")
    blob = result_npz_bytes(sig, {"k": 1})
    with np.load(io.BytesIO(blob)) as z:
        assert int(z["sample_rate_hz"]) == 1000
        assert json.loads(bytes(z["metadata_json"]).decode()) == {"k": 1}
    csv_text = rows_to_csv([{"a": 1, "b": 2}, {"a": 3, "c": 4}])
    assert csv_text.splitlines()[0] == "a,b,c"
    assert rows_to_csv([]) == ""
