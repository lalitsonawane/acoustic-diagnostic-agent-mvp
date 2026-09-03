"""Persistent run history and structured audit log (SQLite).

The Streamlit session holds an in-memory run log for the current browser tab.
This module keeps the same rows (plus approval events) on disk so History /
Trends survive reloads and can be exported beyond the session.

Storage path
------------
Resolved in order:

1. Explicit ``path`` argument to :class:`RunStore`.
2. ``ACOUSTIC_AGENT_DATA_DIR`` environment variable (directory; file is
   ``history.sqlite3`` inside it).
3. Platform user cache: ``~/.cache/acoustic_agent/history.sqlite3`` (Linux),
   or the equivalent under ``XDG_CACHE_HOME`` / macOS / Windows.

On ephemeral hosts (Streamlit Community Cloud, Render free disks) the file is
lost on restart unless a persistent volume is mounted and
``ACOUSTIC_AGENT_DATA_DIR`` points at it. Exports (JSONL / CSV) remain the
durable record in that case.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  analysed_at TEXT NOT NULL,
  asset TEXT NOT NULL,
  source TEXT NOT NULL,
  state TEXT NOT NULL,
  score REAL,
  confidence REAL,
  driver TEXT,
  config_hash TEXT,
  feature_version TEXT,
  baseline TEXT,
  payload_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runs_asset_time ON runs (asset, analysed_at);
CREATE INDEX IF NOT EXISTS idx_runs_time ON runs (analysed_at);

CREATE TABLE IF NOT EXISTS audit_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_at TEXT NOT NULL,
  event_type TEXT NOT NULL,
  ticket_id TEXT,
  asset TEXT,
  actor TEXT,
  payload_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_events (event_at);
CREATE INDEX IF NOT EXISTS idx_audit_type ON audit_events (event_type);
"""


def default_data_dir() -> Path:
    """Directory that holds ``history.sqlite3`` when no override is set."""
    override = os.environ.get("ACOUSTIC_AGENT_DATA_DIR")
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg) / "acoustic_agent"
    return Path.home() / ".cache" / "acoustic_agent"


def default_db_path() -> Path:
    return default_data_dir() / "history.sqlite3"


@dataclass(frozen=True)
class TrendPoint:
    analysed_at: str
    score: float
    state: str
    confidence: float
    source: str
    run_id: int


class RunStore:
    """SQLite-backed history of analyses and audit events.

    Safe to share across Streamlit sessions on the same host; each method opens
    a short-lived connection. Not a multi-writer production database.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
                    (str(SCHEMA_VERSION),),
                )
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('updated_at', ?)",
                (datetime.now(UTC).isoformat(timespec="seconds"),),
            )

    # --- runs -----------------------------------------------------------------

    def append_run(self, row: dict[str, Any]) -> int:
        """Persist one analysis summary row. Returns the new run id."""
        payload = dict(row)
        analysed_at = str(payload.get("analysed_at") or datetime.now(UTC).isoformat(timespec="seconds"))
        asset = str(payload.get("profile") or payload.get("asset") or "unknown")
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO runs (
                  analysed_at, asset, source, state, score, confidence, driver,
                  config_hash, feature_version, baseline, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    analysed_at,
                    asset,
                    str(payload.get("source") or ""),
                    str(payload.get("state") or ""),
                    _as_float(payload.get("score")),
                    _as_float(payload.get("confidence")),
                    str(payload.get("driver") or "") or None,
                    str(payload.get("config_hash") or "") or None,
                    str(payload.get("feature_version") or "") or None,
                    str(payload.get("baseline") or "") or None,
                    json.dumps(payload, default=str),
                ),
            )
            if cur.lastrowid is None:  # pragma: no cover
                raise RuntimeError("SQLite did not return a run id")
            run_id = int(cur.lastrowid)
            conn.execute(
                """
                INSERT INTO audit_events (event_at, event_type, ticket_id, asset, actor, payload_json)
                VALUES (?, 'analysis', NULL, ?, 'system', ?)
                """,
                (
                    analysed_at,
                    asset,
                    json.dumps({"run_id": run_id, "state": payload.get("state"), "score": payload.get("score")}, default=str),
                ),
            )
            return run_id

    def list_runs(
        self,
        *,
        asset: str | None = None,
        limit: int = 500,
        since: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if asset:
            clauses.append("asset = ?")
            params.append(asset)
        if since:
            clauses.append("analysed_at >= ?")
            params.append(since)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, int(limit)))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, analysed_at, asset, source, state, score, confidence, driver,
                       config_hash, feature_version, baseline, payload_json
                FROM runs {where}
                ORDER BY analysed_at DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [_run_row_to_dict(r) for r in rows]

    def assets(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT DISTINCT asset FROM runs ORDER BY asset").fetchall()
        return [str(r["asset"]) for r in rows]

    def asset_trend(self, asset: str, *, limit: int = 200) -> list[TrendPoint]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, analysed_at, score, state, confidence, source
                FROM runs
                WHERE asset = ?
                ORDER BY analysed_at ASC, id ASC
                LIMIT ?
                """,
                (asset, max(1, int(limit))),
            ).fetchall()
        points: list[TrendPoint] = []
        for r in rows:
            score = r["score"]
            if score is None:
                continue
            points.append(
                TrendPoint(
                    analysed_at=str(r["analysed_at"]),
                    score=float(score),
                    state=str(r["state"]),
                    confidence=float(r["confidence"] if r["confidence"] is not None else 0.0),
                    source=str(r["source"]),
                    run_id=int(r["id"]),
                )
            )
        return points

    def run_count(self) -> int:
        with self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0])

    # --- audit / approvals ----------------------------------------------------

    def append_approval(self, payload: dict[str, Any], *, actor: str = "simulated-planner") -> int:
        """Record a planner approval (or rejection) as a structured audit event."""
        event_at = str(payload.get("approved_at") or payload.get("event_at") or datetime.now(UTC).isoformat(timespec="seconds"))
        event_type = str(payload.get("event_type") or "approval")
        ticket_id = payload.get("ticket_id")
        asset = payload.get("asset") or payload.get("profile")
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO audit_events (event_at, event_type, ticket_id, asset, actor, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event_at,
                    event_type,
                    str(ticket_id) if ticket_id else None,
                    str(asset) if asset else None,
                    actor,
                    json.dumps(payload, default=str),
                ),
            )
            if cur.lastrowid is None:  # pragma: no cover
                raise RuntimeError("SQLite did not return an audit event id")
            return int(cur.lastrowid)

    def list_audit_events(
        self,
        *,
        event_type: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, int(limit)))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, event_at, event_type, ticket_id, asset, actor, payload_json
                FROM audit_events {where}
                ORDER BY event_at DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [_audit_row_to_dict(r) for r in rows]

    def export_audit_jsonl(self, *, limit: int = 10_000) -> str:
        """Newline-delimited JSON audit trail (newest first)."""
        events = self.list_audit_events(limit=limit)
        return "\n".join(json.dumps(e, default=str) for e in events) + ("\n" if events else "")

    def export_runs_csv(self, *, asset: str | None = None, limit: int = 10_000) -> str:
        from acoustic_agent.io import rows_to_csv

        return rows_to_csv(self.list_runs(asset=asset, limit=limit))

    def export_audit_csv(self, *, limit: int = 10_000) -> str:
        from acoustic_agent.io import rows_to_csv

        flat: list[dict[str, Any]] = []
        for event in self.list_audit_events(limit=limit):
            flat.append(
                {
                    "id": event["id"],
                    "event_at": event["event_at"],
                    "event_type": event["event_type"],
                    "ticket_id": event.get("ticket_id"),
                    "asset": event.get("asset"),
                    "actor": event.get("actor"),
                    "payload_json": json.dumps(event.get("payload") or {}, default=str),
                }
            )
        return rows_to_csv(flat)

    def clear(self) -> None:
        """Delete all runs and audit events (keeps the schema)."""
        with self._connect() as conn:
            conn.execute("DELETE FROM runs")
            conn.execute("DELETE FROM audit_events")
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('updated_at', ?)",
                (datetime.now(UTC).isoformat(timespec="seconds"),),
            )

    def import_run_rows(self, rows: Iterable[dict[str, Any]]) -> int:
        """Bulk-import summary rows (e.g. a previously exported CSV/JSON). Returns count."""
        count = 0
        for row in rows:
            self.append_run(row)
            count += 1
        return count


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _run_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    payload = cast(dict[str, Any], json.loads(row["payload_json"]))
    payload.update(
        {
            "id": int(row["id"]),
            "analysed_at": row["analysed_at"],
            "asset": row["asset"],
            "profile": payload.get("profile") or row["asset"],
            "source": row["source"],
            "state": row["state"],
            "score": row["score"],
            "confidence": row["confidence"],
            "driver": row["driver"],
            "config_hash": row["config_hash"],
            "feature_version": row["feature_version"],
            "baseline": row["baseline"],
        }
    )
    return payload


def _audit_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "event_at": row["event_at"],
        "event_type": row["event_type"],
        "ticket_id": row["ticket_id"],
        "asset": row["asset"],
        "actor": row["actor"],
        "payload": cast(dict[str, Any], json.loads(row["payload_json"])),
    }
