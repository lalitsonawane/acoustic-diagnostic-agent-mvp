from __future__ import annotations

import json
from pathlib import Path

import pytest

from acoustic_agent import __version__
from acoustic_agent.cli import main
from acoustic_agent.config import ExperimentConfig
from acoustic_agent.detect import Baseline
from acoustic_agent.pipeline import analyze_synthetic
from acoustic_agent.plots import (
    PlotTheme,
    channel_contributions_png,
    envelope_spectrum_png,
    psd_overlay_png,
    spectrogram_png,
    waveform_png,
)
from acoustic_agent.synth import healthy_reference

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# --- CLI ----------------------------------------------------------------------------------


def test_cli_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_cli_analyze_synthetic_json(capsys):
    assert main(["analyze", "--synthetic", "--inject-bursts", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["state"] == "CRITICAL"
    assert payload["decision"]["actionable"] is True


def test_cli_analyze_file_text(capsys, samples_dir: Path):
    assert main(["analyze", str(samples_dir / "robotic_arm_healthy_48k.wav")]) == 0
    out = capsys.readouterr().out
    assert "state         : HEALTHY" in out
    assert "config hash" in out


def test_cli_analyze_requires_path_or_synthetic(capsys):
    assert main(["analyze"]) == 2
    assert "provide a WAV path" in capsys.readouterr().err


def test_cli_analyze_missing_file(capsys, tmp_path: Path):
    assert main(["analyze", str(tmp_path / "missing.wav")]) == 1


def test_cli_batch_writes_csv(capsys, samples_dir: Path, tmp_path: Path):
    out = tmp_path / "batch.csv"
    assert main(["batch", str(samples_dir), "--out", str(out)]) == 0
    captured = capsys.readouterr()
    assert out.exists() and out.read_text().startswith("analysed_at,")
    assert "ROC AUC" in captured.err
    assert "excluded from metrics" in captured.err


def test_cli_sweep_json(capsys):
    assert main(["sweep", "--parameter", "noise_std", "--values", "0.01,0.03", "--seeds", "1", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [r["value"] for r in rows] == [0.01, 0.03]
    assert all("separation" in r for r in rows)


def test_cli_config_roundtrip(capsys, tmp_path: Path):
    exported = tmp_path / "cfg.yaml"
    assert main(["config", "--profile", "Stamping Press", "--seed", "9", "--export", str(exported)]) == 0
    cfg = ExperimentConfig.load(exported)
    assert cfg.profile == "Stamping Press" and cfg.seed == 9
    # and consume it again
    assert main(["config", "--config", str(exported), "--list-sweepable"]) == 0
    out = capsys.readouterr().out
    assert "profile: Stamping Press" in out and "noise_std" in out


def test_cli_invalid_config_is_exit_2(capsys, tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"warn_threshold": 90, "critical_threshold": 10}))
    assert main(["config", "--config", str(bad)]) == 2
    assert "error:" in capsys.readouterr().err


def test_cli_calibrate(capsys):
    assert main(["calibrate", "--profile", "Conveyor Drive"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["n"] == ExperimentConfig().baseline_seeds
    assert "config_hash" in payload


# --- plots --------------------------------------------------------------------------------


def _is_png(blob: bytes) -> bool:
    return blob.startswith(PNG_MAGIC) and len(blob) > 1000


def test_all_plots_render_png(config: ExperimentConfig, baseline: Baseline):
    cfg = config.with_updates(inject_bearing_impacts=True, duration_s=0.5)
    res = analyze_synthetic(cfg, baseline)
    healthy = healthy_reference(cfg, 10_000)
    for theme in (PlotTheme(), PlotTheme.light()):
        assert _is_png(spectrogram_png(res.signal, cfg, theme))
        assert _is_png(waveform_png(res.signal, cfg, theme))
        assert _is_png(psd_overlay_png(res.signal, cfg, healthy, theme=theme))
        assert _is_png(psd_overlay_png(res.signal, cfg, None, theme=theme))
        assert _is_png(envelope_spectrum_png(res.signal, cfg, theme=theme, expected_hz=cfg.shaft_hz * cfg.bpfo_ratio))
        assert _is_png(channel_contributions_png(res.detection.z_by_channel, cfg.weights, baseline, cfg, theme=theme))


def test_plots_survive_low_sample_rate(config: ExperimentConfig):
    """At 16 kHz the diagnostic band lies above Nyquist; shading must degrade gracefully."""
    cfg = config.with_updates(sample_rate_hz=16_000, duration_s=0.5, baseline_seeds=2)
    res = analyze_synthetic(cfg)
    assert _is_png(spectrogram_png(res.signal, cfg))
    assert _is_png(psd_overlay_png(res.signal, cfg, None))
    assert _is_png(channel_contributions_png(res.detection.z_by_channel, cfg.weights, res.baseline, cfg))
