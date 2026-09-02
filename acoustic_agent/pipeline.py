"""End-to-end analysis shared by the Streamlit app and the CLI."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np

from acoustic_agent import FEATURE_VERSION
from acoustic_agent.config import ExperimentConfig, config_hash
from acoustic_agent.decision import Decision, decide
from acoustic_agent.detect import Baseline, Detection, calibrate_baseline, score_features
from acoustic_agent.features import FeatureSet, extract_features
from acoustic_agent.metrics import ClassificationReport, classification_report
from acoustic_agent.synth import Signal, synthesize
from acoustic_agent.validate import Validity, assess_validity


@dataclass(frozen=True)
class AnalysisResult:
    signal: Signal
    features: FeatureSet
    validity: Validity
    detection: Detection
    decision: Decision
    baseline: Baseline
    config: ExperimentConfig
    analysed_at: datetime
    steps: list[tuple[str, datetime]] = field(default_factory=list)

    @property
    def score(self) -> float:
        return self.detection.score

    @property
    def state(self) -> str:
        return self.decision.state

    def summary_row(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        """Flat dictionary for run logs and CSV export."""
        row: dict[str, Any] = {
            "analysed_at": self.analysed_at.isoformat(timespec="seconds"),
            "source": self.signal.source,
            "profile": self.config.profile,
            "state": self.decision.state,
            "score": round(self.detection.score, 2),
            "raw_score": round(self.detection.raw_score, 2),
            "confidence": round(self.validity.confidence, 3),
            "driver": self.detection.driver or "",
            "z_combined": round(self.detection.z_combined, 3),
            "rul_days": self.decision.rul_days,
            "sample_rate_hz": self.signal.sample_rate_hz,
            "duration_s": round(self.signal.duration_s, 3),
            "demo_boost": self.detection.demo_boost,
            "flags": ";".join(self.validity.flags),
            "config_hash": config_hash(self.config),
            "feature_version": FEATURE_VERSION,
        }
        for name, value in self.features.channels().items():
            row[f"feat_{name}"] = round(float(value), 4) if np.isfinite(value) else None
        row["feat_envelope_peak_hz"] = round(self.features.envelope_peak_hz, 2) if np.isfinite(self.features.envelope_peak_hz) else None
        for name, value in self.detection.z_by_channel.items():
            row[f"z_{name}"] = round(float(value), 3) if np.isfinite(value) else None
        if extra:
            row.update(extra)
        return row

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary_row(),
            "features": self.features.as_dict(),
            "validity": {
                "valid": self.validity.valid,
                "confidence": self.validity.confidence,
                "flags": self.validity.flags,
                "warnings": self.validity.warnings,
            },
            "detection": self.detection.to_dict(),
            "decision": self.decision.to_dict(),
            "baseline": self.baseline.to_dict(),
            "config": self.config.to_dict(),
            "steps": [(name, ts.isoformat(timespec="milliseconds")) for name, ts in self.steps],
        }


def analyze(signal: Signal, config: ExperimentConfig, baseline: Baseline | None = None) -> AnalysisResult:
    """Feature extraction -> validity -> scoring -> decision, with real step timestamps."""
    steps: list[tuple[str, datetime]] = []

    def mark(name: str) -> None:
        steps.append((name, datetime.now(UTC)))

    mark("Signal received")
    baseline = baseline or calibrate_baseline(config)
    mark(f"Baseline ready ({baseline.source})")
    features = extract_features(signal.audio, signal.sample_rate_hz, config)
    mark("Features extracted (Welch PSD, residual statistics, envelope spectrum)")
    validity = assess_validity(features, config)
    mark("Input validity assessed")
    detection = score_features(features, baseline, config)
    mark("Anomaly score computed")
    decision = decide(detection, validity, config.machine(), config)
    mark(f"Decision: {decision.state}")
    return AnalysisResult(
        signal=signal,
        features=features,
        validity=validity,
        detection=detection,
        decision=decision,
        baseline=baseline,
        config=config,
        analysed_at=steps[0][1],
        steps=steps,
    )


def analyze_synthetic(config: ExperimentConfig, baseline: Baseline | None = None) -> AnalysisResult:
    return analyze(synthesize(config), config, baseline)


@dataclass
class BatchResult:
    rows: list[dict[str, Any]]
    results: list[AnalysisResult]
    report: ClassificationReport | None
    skipped: list[str] = field(default_factory=list)


def run_batch(
    signals: list[tuple[Signal, int | None]],
    config: ExperimentConfig,
    baseline: Baseline | None = None,
) -> BatchResult:
    """Score many labelled signals with one shared baseline and compute ROC/PR metrics."""
    baseline = baseline or calibrate_baseline(config)
    rows: list[dict[str, Any]] = []
    results: list[AnalysisResult] = []
    labels: list[int] = []
    scores: list[float] = []
    skipped: list[str] = []
    for signal, label in signals:
        result = analyze(signal, config, baseline)
        results.append(result)
        row = result.summary_row({"label": label})
        rows.append(row)
        if label is None or not result.validity.valid:
            skipped.append(signal.source)
            continue
        labels.append(int(label))
        scores.append(result.detection.score)
    report = classification_report(np.array(labels), np.array(scores), config.critical_threshold) if labels else None
    return BatchResult(rows=rows, results=results, report=report, skipped=skipped)


@dataclass
class SweepPoint:
    value: float
    fault_scores: list[float]
    healthy_scores: list[float]

    def row(self) -> dict[str, float]:
        f = np.array(self.fault_scores)
        h = np.array(self.healthy_scores)
        return {
            "value": self.value,
            "fault_mean": float(f.mean()),
            "fault_min": float(f.min()),
            "fault_max": float(f.max()),
            "healthy_mean": float(h.mean()),
            "healthy_min": float(h.min()),
            "healthy_max": float(h.max()),
            "separation": float(f.mean() - h.mean()),
        }


def sweep(
    config: ExperimentConfig,
    parameter: str,
    values: list[float],
    seeds: int = 3,
    fault_mode: str = "bursts",
) -> list[SweepPoint]:
    """Vary one parameter; score fault and healthy renders for several seeds at each value.

    The baseline is recalibrated per value when the parameter affects healthy signals
    (noise, duration), so the sweep measures detector behaviour rather than baseline drift.
    """
    if not hasattr(config, parameter):
        raise ValueError(f"Unknown parameter {parameter!r}")
    points: list[SweepPoint] = []
    inject = {"inject_bursts": fault_mode == "bursts", "inject_bearing_impacts": fault_mode == "bearing"}
    for value in values:
        cfg = config.with_updates(**{parameter: type(getattr(config, parameter))(value)}, **inject)
        cfg.validate()
        baseline = calibrate_baseline(cfg)
        fault_scores: list[float] = []
        healthy_scores: list[float] = []
        for k in range(seeds):
            seed = cfg.seed + 101 * k
            fault_sig = synthesize(cfg, seed=seed)
            healthy_sig = synthesize(cfg, seed=seed, inject_bursts=False, inject_bearing_impacts=False)
            fault_scores.append(analyze(fault_sig, cfg, baseline).score)
            healthy_scores.append(analyze(healthy_sig, cfg, baseline).score)
        points.append(SweepPoint(value=float(value), fault_scores=fault_scores, healthy_scores=healthy_scores))
    return points
