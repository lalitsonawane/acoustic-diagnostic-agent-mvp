"""Streamlit AppTest smoke tests: the UI must drive the package without exceptions."""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")
TIMEOUT = 60


@pytest.fixture
def at() -> AppTest:
    app = AppTest.from_file(APP, default_timeout=TIMEOUT)
    app.run()
    assert not app.exception
    return app


def test_initial_render_shows_healthy_demo_signal(at: AppTest):
    """First load renders a healthy synthetic signal so the page is never empty."""
    sig = at.session_state["signal"]
    assert sig is not None and sig.source.endswith(":healthy")
    assert at.session_state["cfg"]["profile"] == "Robotic Arm Bearings"
    assert at.session_state["run_log"][-1]["state"] == "HEALTHY"
    assert any("Generate" in b.label for b in at.button)


def test_generate_with_new_seed_logs_second_healthy_run(at: AppTest):
    at.number_input(key="w_seed").set_value(7).run()
    assert at.session_state["cfg"]["seed"] == 7
    at.button(key="generate").click().run()
    assert not at.exception
    log = at.session_state["run_log"]
    # Row 1: initial demo signal. Row 2: same signal re-scored under the new config hash.
    # Row 3: the freshly generated seed=7 signal. Every (signal, config) pair is logged once.
    assert len(log) == 3 and log[-1]["state"] == "HEALTHY"
    assert "seed=7" in log[-1]["source"]
    assert len({(r["source"], r["config_hash"]) for r in log}) == 3


def test_inject_bursts_and_generate_is_critical(at: AppTest):
    at.toggle(key="w_inject_bursts").set_value(True).run()
    assert at.session_state["cfg"]["inject_bursts"] is True
    at.button(key="generate").click().run()
    assert not at.exception
    row = at.session_state["run_log"][-1]
    assert row["state"] == "CRITICAL" and row["z_band_contrast_db"] > 4
    # the work-order approval gate is rendered only for actionable verdicts
    assert any(b.key == "approve" for b in at.button)


def test_bearing_fault_detected_via_envelope(at: AppTest):
    at.toggle(key="w_inject_bearing_impacts").set_value(True).run()
    at.button(key="generate").click().run()
    assert not at.exception
    row = at.session_state["run_log"][-1]
    assert row["state"] == "CRITICAL"
    assert row["driver"] in {"envelope_peak_snr_db", "residual_kurtosis", "residual_crest_factor"}


def test_sample_library_low_rate_edge_case(at: AppTest):
    at.session_state["source_mode"] = "Sample library"
    at.run()
    at.selectbox(key="sample_choice").select("robotic_arm_fault_16k.wav").run()
    at.button(key="load_sample").click().run()
    assert not at.exception
    row = at.session_state["run_log"][-1]
    assert row["sample_rate_hz"] == 16_000
    assert "band_unavailable" in row["flags"]
    assert row["state"] != "CRITICAL"  # never actionable on aliased input


def test_widget_values_survive_mode_switch(at: AppTest):
    at.toggle(key="w_inject_bursts").set_value(True).run()
    at.session_state["source_mode"] = "Upload"
    at.run()
    at.session_state["source_mode"] = "Simulate"
    at.run()
    assert not at.exception
    assert at.session_state["cfg"]["inject_bursts"] is True
    assert at.toggle(key="w_inject_bursts").value is True
