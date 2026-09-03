"""Tests for the SQLite run history / audit store."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from acoustic_agent.store import RunStore, default_data_dir, default_db_path


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RunStore:
    monkeypatch.setenv("ACOUSTIC_AGENT_DATA_DIR", str(tmp_path / "data"))
    return RunStore()


def _row(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "analysed_at": "2026-09-03T10:00:00+00:00",
        "source": "synth:demo",
        "profile": "Robotic Arm Bearings",
        "state": "HEALTHY",
        "score": 12.5,
        "confidence": 1.0,
        "driver": "band_contrast_db",
        "config_hash": "abc123",
        "feature_version": "features-v3-welch-transient-envelope",
        "baseline": "synthetic:8",
    }
    base.update(overrides)
    return base


def test_default_paths_respect_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ACOUSTIC_AGENT_DATA_DIR", str(tmp_path / "custom"))
    assert default_data_dir() == tmp_path / "custom"
    assert default_db_path() == tmp_path / "custom" / "history.sqlite3"


def test_append_and_list_runs(store: RunStore) -> None:
    run_id = store.append_run(_row())
    assert run_id >= 1
    store.append_run(_row(analysed_at="2026-09-03T11:00:00+00:00", state="CRITICAL", score=88.0))
    runs = store.list_runs()
    assert len(runs) == 2
    assert runs[0]["state"] == "CRITICAL"  # newest first
    assert runs[0]["id"] == 2
    assert store.run_count() == 2
    assert store.assets() == ["Robotic Arm Bearings"]


def test_asset_filter_and_trend(store: RunStore) -> None:
    store.append_run(_row(analysed_at="2026-09-03T09:00:00+00:00", score=10.0))
    store.append_run(_row(analysed_at="2026-09-03T10:00:00+00:00", score=40.0, state="WARNING"))
    store.append_run(
        _row(
            analysed_at="2026-09-03T10:30:00+00:00",
            profile="Stamping Press",
            score=20.0,
        )
    )
    arm = store.list_runs(asset="Robotic Arm Bearings")
    assert len(arm) == 2
    trend = store.asset_trend("Robotic Arm Bearings")
    assert [p.score for p in trend] == [10.0, 40.0]
    assert trend[0].analysed_at < trend[1].analysed_at


def test_approval_audit_and_exports(store: RunStore) -> None:
    store.append_run(_row(state="CRITICAL", score=91.0))
    store.append_approval(
        {
            "ticket_id": "WO-20260903-ABCDEF12",
            "asset": "Robotic Arm Bearings",
            "approved_at": "2026-09-03T12:00:00+00:00",
            "status": "APPROVED (simulated)",
            "anomaly_score_pct": 91.0,
        }
    )
    approvals = store.list_audit_events(event_type="approval")
    assert len(approvals) == 1
    assert approvals[0]["ticket_id"] == "WO-20260903-ABCDEF12"
    assert approvals[0]["actor"] == "simulated-planner"

    all_events = store.list_audit_events()
    assert {e["event_type"] for e in all_events} == {"analysis", "approval"}

    jsonl = store.export_audit_jsonl()
    lines = [ln for ln in jsonl.strip().splitlines() if ln]
    assert len(lines) == 2
    assert json.loads(lines[0])["event_type"] in {"analysis", "approval"}

    runs_csv = store.export_runs_csv()
    assert "Robotic Arm Bearings" in runs_csv
    assert "score" in runs_csv.splitlines()[0]

    audit_csv = store.export_audit_csv()
    assert "ticket_id" in audit_csv.splitlines()[0]
    assert "WO-20260903-ABCDEF12" in audit_csv


def test_clear_and_import(store: RunStore) -> None:
    store.append_run(_row())
    store.clear()
    assert store.run_count() == 0
    assert store.list_audit_events() == []
    n = store.import_run_rows([_row(score=5.0), _row(analysed_at="2026-09-03T13:00:00+00:00", score=6.0)])
    assert n == 2
    assert store.run_count() == 2


def test_explicit_path(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "hist.db"
    store = RunStore(path)
    store.append_run(_row())
    assert path.exists()
    reopened = RunStore(path)
    assert reopened.run_count() == 1
