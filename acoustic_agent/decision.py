"""Turn a score plus validity into a maintenance decision.

States
------
INVALID   input failed a hard validity check; no verdict.
HEALTHY   score <= warn threshold.
WARNING   warn < score <= critical.
CRITICAL  score > critical **and** confidence >= min_confidence -> work order proposed.
CRITICAL (unconfirmed)
          score > critical but confidence too low -> re-measure, no work order.

The work-order payload is a mock of what would be sent to SAP S/4HANA PM. It carries a
UUID-derived id, real timestamps, the configuration hash and feature version so that any
proposed action can be traced back to the exact analysis that produced it.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from acoustic_agent import FEATURE_VERSION, __version__
from acoustic_agent.config import ExperimentConfig, MachineProfile, config_hash
from acoustic_agent.detect import Detection
from acoustic_agent.validate import Validity

STATE_COLORS: dict[str, str] = {
    "INVALID": "gray",
    "HEALTHY": "green",
    "WARNING": "orange",
    "CRITICAL": "red",
    "CRITICAL (unconfirmed)": "orange",
}

STATE_ICONS: dict[str, str] = {
    "INVALID": ":material/block:",
    "HEALTHY": ":material/check_circle:",
    "WARNING": ":material/warning:",
    "CRITICAL": ":material/error:",
    "CRITICAL (unconfirmed)": ":material/help:",
}


@dataclass(frozen=True)
class Decision:
    state: str
    actionable: bool
    recommended_action: str
    explanation: str
    rul_days: int | None
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def health_state(score: float, confidence: float, valid: bool, config: ExperimentConfig) -> str:
    if not valid:
        return "INVALID"
    if score > config.critical_threshold:
        return "CRITICAL" if confidence >= config.min_confidence else "CRITICAL (unconfirmed)"
    if score > config.warn_threshold:
        return "WARNING"
    return "HEALTHY"


def illustrative_rul_days(profile: MachineProfile, score: float) -> int:
    """Illustrative remaining-useful-life estimate; not a survival model."""
    return max(3, int(profile.nominal_rul_days * (1.0 - score / 125.0)))


_CHANNEL_LABELS = {
    "band_contrast_db": "ultrasonic band contrast",
    "band_contrast_transient_db": "short ultrasonic bursts (time-resolved band contrast)",
    "band_power_db": "ultrasonic band power",
    "envelope_peak_snr_db": "periodic impact pattern in the envelope spectrum",
    "residual_kurtosis": "impulsiveness (kurtosis) of the high-frequency residual",
    "residual_crest_factor": "peakiness (crest factor) of the high-frequency residual",
}


def explain(detection: Detection, validity: Validity, state: str) -> str:
    if state == "INVALID":
        return validity.warnings[0] if validity.warnings else "Input could not be analysed."
    parts: list[str] = []
    z = detection.z_by_channel.get(detection.driver, 0.0) if detection.driver else 0.0
    if detection.driver and z >= 1.0:
        parts.append(
            f"Strongest evidence: {_CHANNEL_LABELS.get(detection.driver, detection.driver)} is "
            f"{z:.1f} standard deviations above the healthy baseline."
        )
    else:
        parts.append("No channel deviates meaningfully from the healthy baseline.")
    if detection.demo_boost > 0:
        parts.append(f"A teaching demo boost of +{detection.demo_boost:.0f} points was added; this is not a measurement.")
    if validity.warnings:
        parts.append(f"Confidence reduced to {validity.confidence:.0%}: " + " ".join(validity.warnings))
    return " ".join(parts)


def recommended_action(state: str) -> str:
    return {
        "INVALID": "Check the sensor and capture chain, then re-record. No verdict was issued.",
        "HEALTHY": "No maintenance action. Continue scheduled monitoring.",
        "WARNING": "Increase monitoring frequency and schedule a follow-up capture within the shift.",
        "CRITICAL": "Propose a P1 maintenance work order for planner approval.",
        "CRITICAL (unconfirmed)": (
            "Critical signature detected but input quality is too low to act on. Re-capture with a valid "
            "sample rate / gain before a work order is proposed."
        ),
    }[state]


def decide(detection: Detection, validity: Validity, profile: MachineProfile, config: ExperimentConfig) -> Decision:
    state = health_state(detection.score, validity.confidence, validity.valid, config)
    rul = None if state == "INVALID" else illustrative_rul_days(profile, detection.score)
    return Decision(
        state=state,
        actionable=state == "CRITICAL",
        recommended_action=recommended_action(state),
        explanation=explain(detection, validity, state),
        rul_days=rul,
        confidence=validity.confidence,
    )


def work_order_payload(
    profile: MachineProfile,
    detection: Detection,
    decision: Decision,
    config: ExperimentConfig,
    *,
    now: datetime | None = None,
    source: str = "",
) -> dict[str, Any]:
    """Mock SAP S/4HANA PM maintenance-request payload. Nothing is sent anywhere."""
    now = now or datetime.now(UTC)
    window_start = now + timedelta(days=2)
    return {
        "ticket_id": f"WO-{now:%Y%m%d}-{uuid.uuid4().hex[:8].upper()}",
        "created_at": now.isoformat(timespec="seconds"),
        "system": "SAP S/4HANA PM (mock)",
        "status": "PROPOSED - awaiting planner approval",
        "asset": profile.name,
        "material_part_number": profile.part,
        "priority": "P1 - Immediate maintenance" if decision.actionable else "n/a",
        "suggested_window_start": window_start.replace(hour=22, minute=0, second=0, microsecond=0).isoformat(timespec="minutes"),
        "suggested_window_end": window_start.replace(hour=23, minute=30, second=0, microsecond=0).isoformat(timespec="minutes"),
        "anomaly_score_pct": round(detection.score, 1),
        "confidence": round(decision.confidence, 2),
        "state": decision.state,
        "evidence_driver": detection.driver,
        "z_combined": round(detection.z_combined, 2),
        "demo_boost_applied": detection.demo_boost > 0,
        "source": source,
        "config_hash": config_hash(config),
        "feature_version": FEATURE_VERSION,
        "software_version": __version__,
    }
