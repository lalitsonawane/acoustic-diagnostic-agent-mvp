"""Headless command-line interface sharing the core pipeline with the Streamlit app.

Examples
--------
    acoustic-agent analyze data/samples/robotic_arm_fault_48k.wav
    acoustic-agent analyze --synthetic --inject-bursts --json
    acoustic-agent batch data/samples --manifest data/samples/manifest.csv --out results.csv
    acoustic-agent sweep --parameter burst_amplitude --values 0,0.05,0.1,0.2,0.42
    acoustic-agent config --export experiment.yaml
    acoustic-agent calibrate --config experiment.yaml
    acoustic-agent history --asset "Robotic Arm Bearings"
    acoustic-agent audit --format jsonl --out audit.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from acoustic_agent import __version__
from acoustic_agent.config import ExperimentConfig, config_hash, sweepable_parameters
from acoustic_agent.detect import calibrate_baseline
from acoustic_agent.io import AudioLoadError, labels_from_manifest_text, load_audio, load_sample_manifest, rows_to_csv
from acoustic_agent.pipeline import AnalysisResult, analyze, run_batch, sweep
from acoustic_agent.store import RunStore, default_db_path
from acoustic_agent.synth import Signal, synthesize


def _load_config(args: argparse.Namespace) -> ExperimentConfig:
    cfg = ExperimentConfig.load(args.config) if getattr(args, "config", None) else ExperimentConfig()
    if getattr(args, "profile", None):
        cfg = cfg.with_updates(profile=args.profile)
    if getattr(args, "inject_bursts", False):
        cfg = cfg.with_updates(inject_bursts=True)
    if getattr(args, "inject_bearing", False):
        cfg = cfg.with_updates(inject_bearing_impacts=True)
    if getattr(args, "seed", None) is not None:
        cfg = cfg.with_updates(seed=args.seed)
    cfg.validate()
    return cfg


def _print_result(result: AnalysisResult, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result.to_dict(), indent=2, default=str))
        return
    d, det, v = result.decision, result.detection, result.validity
    print(f"source        : {result.signal.source}")
    print(f"state         : {d.state}")
    print(f"score         : {det.score:.1f} %  (raw {det.raw_score:.1f}, z = {det.z_combined:.2f}, driver = {det.driver})")
    print(f"confidence    : {v.confidence:.2f}  flags = {', '.join(v.flags) or 'none'}")
    print(f"RUL (illustr.): {d.rul_days} days")
    print(f"action        : {d.recommended_action}")
    print(f"config hash   : {config_hash(result.config)}")
    print("features:")
    for name, value in result.features.channels().items():
        z = det.z_by_channel.get(name, float("nan"))
        print(f"  {name:24s} {value:10.3f}   z = {z:7.2f}")
    for warning in v.warnings:
        print(f"warning       : {warning}")


def _store_from_args(args: argparse.Namespace) -> RunStore:
    return RunStore(Path(args.db) if getattr(args, "db", None) else None)


def cmd_analyze(args: argparse.Namespace) -> int:
    cfg = _load_config(args)
    if args.synthetic:
        signal = synthesize(cfg)
    else:
        if not args.path:
            print("error: provide a WAV path or --synthetic", file=sys.stderr)
            return 2
        try:
            signal = load_audio(Path(args.path))
        except (AudioLoadError, OSError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    result = analyze(signal, cfg)
    if getattr(args, "persist", False):
        row = result.summary_row({"baseline": result.baseline.source})
        run_id = _store_from_args(args).append_run(row)
        db = args.db if getattr(args, "db", None) else str(default_db_path())
        print(f"persisted run id {run_id} -> {db}", file=sys.stderr)
    _print_result(result, args.json)
    return 0


def _collect_signals(path: Path, manifest: Path | None) -> list[tuple[Signal, int | None]]:
    if path.is_dir():
        files = sorted(p for p in path.iterdir() if p.suffix.lower() in {".wav", ".flac", ".ogg"})
    else:
        files = [path]
    labels: dict[str, int | None] = {}
    if manifest is not None:
        labels = labels_from_manifest_text(manifest.read_text(encoding="utf-8"))
    elif path.is_dir() and (path / "manifest.csv").exists():
        labels = {e.file: e.label for e in load_sample_manifest(path / "manifest.csv")}
    signals: list[tuple[Signal, int | None]] = []
    for file in files:
        try:
            signals.append((load_audio(file), labels.get(file.name)))
        except AudioLoadError as exc:
            print(f"skip {file.name}: {exc}", file=sys.stderr)
    return signals


def cmd_batch(args: argparse.Namespace) -> int:
    cfg = _load_config(args)
    signals = _collect_signals(Path(args.path), Path(args.manifest) if args.manifest else None)
    if not signals:
        print("error: no audio files found", file=sys.stderr)
        return 1
    batch = run_batch(signals, cfg)
    csv_text = rows_to_csv(batch.rows)
    if args.out:
        Path(args.out).write_text(csv_text, encoding="utf-8")
        print(f"wrote {args.out} ({len(batch.rows)} rows)")
    else:
        print(csv_text, end="")
    if batch.report is not None:
        r = batch.report
        print(
            f"\nlabelled n={r.n_positive + r.n_negative} (fault {r.n_positive}, healthy {r.n_negative}) "
            f"threshold {r.threshold:.0f}: TP {r.tp} FP {r.fp} TN {r.tn} FN {r.fn} | "
            f"precision {r.precision:.2f} recall {r.recall:.2f} F1 {r.f1:.2f}"
            + (f" | ROC AUC {r.roc.auc:.3f} AP {r.pr.auc:.3f}" if r.roc and r.pr else ""),
            file=sys.stderr,
        )
    if batch.skipped:
        print(f"excluded from metrics (unlabelled or invalid): {', '.join(batch.skipped)}", file=sys.stderr)
    return 0


def cmd_sweep(args: argparse.Namespace) -> int:
    cfg = _load_config(args)
    values = [float(v) for v in args.values.split(",") if v.strip()]
    points = sweep(cfg, args.parameter, values, seeds=args.seeds, fault_mode=args.fault_mode)
    rows = [p.row() for p in points]
    text = rows_to_csv(rows) if not args.json else json.dumps(rows, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(text, end="" if not args.json else "\n")
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    cfg = _load_config(args)
    if args.export:
        cfg.save(args.export)
        print(f"wrote {args.export} (hash {config_hash(cfg)})")
    else:
        print(cfg.to_yaml(), end="")
        print(f"# hash: {config_hash(cfg)}")
    if args.list_sweepable:
        for name, desc in sweepable_parameters().items():
            print(f"{name:20s} {desc}")
    return 0


def cmd_calibrate(args: argparse.Namespace) -> int:
    cfg = _load_config(args)
    baseline = calibrate_baseline(cfg)
    payload: dict[str, Any] = baseline.to_dict()
    payload["config_hash"] = config_hash(cfg)
    print(json.dumps(payload, indent=2))
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    store = _store_from_args(args)
    if args.assets:
        for name in store.assets():
            print(name)
        return 0
    if args.trend:
        points = store.asset_trend(args.trend, limit=args.limit)
        rows = [
            {
                "analysed_at": p.analysed_at,
                "score": p.score,
                "state": p.state,
                "confidence": p.confidence,
                "source": p.source,
                "run_id": p.run_id,
            }
            for p in points
        ]
    else:
        rows = store.list_runs(asset=args.asset, limit=args.limit)
    text = json.dumps(rows, indent=2, default=str) if args.json else rows_to_csv(rows)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out} ({len(rows)} rows)")
    else:
        print(text, end="" if not args.json else "\n")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    store = _store_from_args(args)
    if args.format == "jsonl":
        text = store.export_audit_jsonl(limit=args.limit)
    elif args.format == "csv":
        text = store.export_audit_csv(limit=args.limit)
    else:
        text = json.dumps(store.list_audit_events(event_type=args.type, limit=args.limit), indent=2, default=str) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(text, end="")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="acoustic-agent", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--config", help="YAML or JSON ExperimentConfig file")
        p.add_argument("--profile", choices=["Robotic Arm Bearings", "Stamping Press", "Conveyor Drive"])
        p.add_argument("--seed", type=int)

    def add_db(p: argparse.ArgumentParser) -> None:
        p.add_argument("--db", help=f"SQLite path (default: {default_db_path()})")

    p = sub.add_parser("analyze", help="Score one WAV file or a synthetic signal")
    add_common(p)
    add_db(p)
    p.add_argument("path", nargs="?", help="Path to a WAV/FLAC/OGG file")
    p.add_argument("--synthetic", action="store_true", help="Analyse a synthetic render instead of a file")
    p.add_argument("--inject-bursts", action="store_true", help="Synthetic: add 22 kHz micro-crack bursts")
    p.add_argument("--inject-bearing", action="store_true", help="Synthetic: add outer-race bearing impacts")
    p.add_argument("--json", action="store_true", help="Emit the full result as JSON")
    p.add_argument("--persist", action="store_true", help="Append the summary row to the SQLite history store")
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("batch", help="Score a directory (or file) and compute ROC/PR metrics")
    add_common(p)
    p.add_argument("path", help="Directory of audio files or a single file")
    p.add_argument("--manifest", help="CSV with file,condition|label columns (defaults to <dir>/manifest.csv)")
    p.add_argument("--out", help="Write results CSV here instead of stdout")
    p.set_defaults(func=cmd_batch)

    p = sub.add_parser("sweep", help="Vary one parameter and record fault vs healthy scores")
    add_common(p)
    p.add_argument("--parameter", required=True, choices=list(sweepable_parameters()))
    p.add_argument("--values", required=True, help="Comma-separated values")
    p.add_argument("--seeds", type=int, default=3)
    p.add_argument("--fault-mode", choices=["bursts", "bearing"], default="bursts")
    p.add_argument("--json", action="store_true")
    p.add_argument("--out")
    p.set_defaults(func=cmd_sweep)

    p = sub.add_parser("config", help="Print or export the effective configuration")
    add_common(p)
    p.add_argument("--export", help="Write YAML (.yaml/.yml) or JSON (.json)")
    p.add_argument("--list-sweepable", action="store_true")
    p.set_defaults(func=cmd_config)

    p = sub.add_parser("calibrate", help="Print the synthetic healthy baseline statistics")
    add_common(p)
    p.set_defaults(func=cmd_calibrate)

    p = sub.add_parser("history", help="List or export persisted analysis runs")
    add_db(p)
    p.add_argument("--asset", help="Filter by machine profile / asset name")
    p.add_argument("--trend", help="Emit chronological score trend for one asset")
    p.add_argument("--assets", action="store_true", help="List distinct asset names")
    p.add_argument("--limit", type=int, default=500)
    p.add_argument("--json", action="store_true")
    p.add_argument("--out")
    p.set_defaults(func=cmd_history)

    p = sub.add_parser("audit", help="Export the structured audit log (analyses + approvals)")
    add_db(p)
    p.add_argument("--format", choices=["jsonl", "csv", "json"], default="jsonl")
    p.add_argument("--type", help="Filter by event_type (analysis, approval, …)")
    p.add_argument("--limit", type=int, default=10_000)
    p.add_argument("--out")
    p.set_defaults(func=cmd_audit)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
