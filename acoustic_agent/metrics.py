"""Binary classification metrics implemented with NumPy only (no scikit-learn dependency)."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class Curve:
    x: np.ndarray
    y: np.ndarray
    thresholds: np.ndarray
    auc: float


@dataclass
class ClassificationReport:
    n_positive: int
    n_negative: int
    roc: Curve | None
    pr: Curve | None
    threshold: float
    tp: int = 0
    fp: int = 0
    tn: int = 0
    fn: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else float("nan")

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else float("nan")

    @property
    def specificity(self) -> float:
        return self.tn / (self.tn + self.fp) if (self.tn + self.fp) else float("nan")

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) and np.isfinite(p) and np.isfinite(r) else float("nan")

    @property
    def accuracy(self) -> float:
        total = self.tp + self.fp + self.tn + self.fn
        return (self.tp + self.tn) / total if total else float("nan")


def _prepare(labels: np.ndarray, scores: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    y = np.asarray(labels, dtype=int).ravel()
    s = np.asarray(scores, dtype=float).ravel()
    if y.shape != s.shape:
        raise ValueError("labels and scores must have the same length")
    keep = np.isfinite(s)
    return y[keep], s[keep]


def roc_curve(labels: np.ndarray, scores: np.ndarray) -> Curve:
    y, s = _prepare(labels, scores)
    order = np.argsort(-s, kind="mergesort")
    y, s = y[order], s[order]
    distinct = np.r_[np.where(np.diff(s))[0], y.size - 1]
    tps = np.cumsum(y)[distinct]
    fps = (1 + distinct) - tps
    n_pos, n_neg = int(y.sum()), int(y.size - y.sum())
    tpr = np.r_[0.0, tps / n_pos] if n_pos else np.r_[0.0, np.zeros(tps.size)]
    fpr = np.r_[0.0, fps / n_neg] if n_neg else np.r_[0.0, np.zeros(fps.size)]
    thresholds = np.r_[np.inf, s[distinct]]
    auc = float(np.trapezoid(tpr, fpr)) if n_pos and n_neg else float("nan")
    return Curve(x=fpr, y=tpr, thresholds=thresholds, auc=auc)


def pr_curve(labels: np.ndarray, scores: np.ndarray) -> Curve:
    y, s = _prepare(labels, scores)
    order = np.argsort(-s, kind="mergesort")
    y, s = y[order], s[order]
    distinct = np.r_[np.where(np.diff(s))[0], y.size - 1]
    tps = np.cumsum(y)[distinct]
    predicted = 1 + distinct
    n_pos = int(y.sum())
    precision = tps / predicted
    recall = tps / n_pos if n_pos else np.zeros_like(tps, dtype=float)
    # Average precision: step-wise area under the PR curve.
    recall_prev = np.r_[0.0, recall[:-1]]
    ap = float(np.sum((recall - recall_prev) * precision)) if n_pos else float("nan")
    return Curve(x=np.r_[0.0, recall], y=np.r_[1.0, precision], thresholds=np.r_[np.inf, s[distinct]], auc=ap)


def classification_report(labels: np.ndarray, scores: np.ndarray, threshold: float) -> ClassificationReport:
    y, s = _prepare(labels, scores)
    n_pos, n_neg = int(y.sum()), int(y.size - y.sum())
    pred = s > threshold
    report = ClassificationReport(
        n_positive=n_pos,
        n_negative=n_neg,
        roc=None,
        pr=None,
        threshold=threshold,
        tp=int(np.sum(pred & (y == 1))),
        fp=int(np.sum(pred & (y == 0))),
        tn=int(np.sum(~pred & (y == 0))),
        fn=int(np.sum(~pred & (y == 1))),
    )
    if n_pos and n_neg:
        report.roc = roc_curve(y, s)
        report.pr = pr_curve(y, s)
    else:
        report.notes.append("ROC/PR need at least one healthy and one fault example.")
    return report
