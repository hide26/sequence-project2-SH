"""
탐지 파이프라인 코어:
  - 합성 이상 주입 (라벨 없는 데이터 평가용)
  - 합의 투표 (N개 탐지기 동의 집계)
  - 3개 평가지표 (point-wise / point-adjusted / affiliation)
  - 임계값 자동 스윕 (F1 최대 지점)
"""
from __future__ import annotations
import numpy as np


def _mad(a, med=None):
    med = np.median(a) if med is None else med
    return 1.4826 * np.median(np.abs(a - med))


# ----------------------- 합성 이상 주입 ---------------------------
def inject_anomalies(series: np.ndarray, seed: int = 7, count: int | None = None,
                     types=("spike", "levelshift", "variance", "drift")):
    """깨끗한 구간에 알려진 이상을 심어 평가용 라벨을 생성."""
    n = len(series)
    out = series.astype(np.float64).copy()
    labels = np.zeros(n, dtype=np.int8)
    sd = series.std() or 1.0
    rng = np.random.default_rng(seed)
    count = count or max(3, int(n * 0.02))
    events = []
    for _ in range(count):
        typ = types[rng.integers(0, len(types))]
        pos = int(rng.integers(int(n * 0.05), int(n * 0.95)))
        if typ == "spike":
            out[pos] += (3 + rng.random() * 4) * sd * (1 if rng.random() < 0.5 else -1)
            labels[pos] = 1
            events.append({"type": typ, "pos": pos, "len": 1})
        elif typ == "levelshift":
            ln = int(5 + rng.random() * 15)
            mag = (2 + rng.random() * 3) * sd * (1 if rng.random() < 0.5 else -1)
            end = min(n, pos + ln)
            out[pos:end] += mag; labels[pos:end] = 1
            events.append({"type": typ, "pos": pos, "len": end - pos})
        elif typ == "variance":
            ln = int(5 + rng.random() * 12); end = min(n, pos + ln)
            out[pos:end] += (rng.random(end - pos) - 0.5) * 6 * sd
            labels[pos:end] = 1
            events.append({"type": typ, "pos": pos, "len": end - pos})
        else:  # drift
            ln = int(10 + rng.random() * 20); end = min(n, pos + ln)
            slope = (1.5 + rng.random() * 2) * sd / ln * (1 if rng.random() < 0.5 else -1)
            out[pos:end] += slope * np.arange(end - pos)
            labels[pos:end] = 1
            events.append({"type": typ, "pos": pos, "len": end - pos})
    return out, labels, events


# --------------------------- 합의 투표 ----------------------------
def consensus(scores: dict[str, np.ndarray], thresholds: dict[str, float],
              weights: dict[str, float] | None = None):
    """탐지기 합의 집계.

    반환:
      votes        하드 투표 — 임계 넘긴 탐지기 수 (정수)
      flags        탐지기별 0/1 판정
      n_det        탐지기 수
      soft         소프트 합의 점수 — 탐지기 점수의 (가중) 평균, 0~1
      weighted     가중 투표 — 임계 넘긴 탐지기의 가중치 합 (실수)
      weights_used 실제 적용된 가중치
    """
    keys = list(scores.keys())
    n = len(scores[keys[0]])
    votes = np.zeros(n, dtype=np.int16)
    soft = np.zeros(n, dtype=np.float64)
    weighted = np.zeros(n, dtype=np.float64)
    flags = {}

    # 가중치 미지정이면 모두 1.0 (= 균등). 합이 탐지기 수가 되도록 정규화.
    w = {k: float(weights.get(k, 1.0)) if weights else 1.0 for k in keys}
    wsum = sum(w.values()) or 1.0
    wnorm = {k: w[k] / wsum * len(keys) for k in keys}  # 평균 1.0 유지

    for k in keys:
        f = (scores[k] >= thresholds.get(k, 0.5)).astype(np.int8)
        flags[k] = f
        votes += f
        soft += scores[k] * wnorm[k]
        weighted += f * wnorm[k]
    soft /= len(keys)  # 0~1 범위로

    return {
        "votes": votes,
        "flags": flags,
        "n_det": len(keys),
        "soft": soft,
        "weighted": weighted,
        "weights_used": wnorm,
    }


def weights_from_f1(detector_best: dict[str, dict]) -> dict[str, float]:
    """탐지기별 단독 F1을 가중치로. F1이 높은 탐지기에 더 큰 표를 준다.
    F1^2 로 차이를 키워 약한 탐지기의 영향을 줄인다."""
    w = {}
    for k, b in detector_best.items():
        f1 = max(0.0, float(b.get("f1", 0.0)))
        w[k] = f1 ** 2 + 1e-3  # 0 방지
    return w


def sweep_consensus_n(votes: np.ndarray, labels, events, n_det: int):
    """합의 임계 N(1..n_det)을 훑어 각 N의 F1을 계산하고 최적 N을 찾는다.
    '왜 이 N인가'를 데이터로 답하기 위한 곡선."""
    curve = []
    best = {"n": 1, "f1": -1.0, "precision": 0.0, "recall": 0.0}
    for N in range(1, n_det + 1):
        flags = (votes >= N).astype(np.int8)
        m = evaluate(labels, flags, point_adjust=True, events=events)
        row = {"n": N, "f1": m["f1"], "precision": m["precision"],
               "recall": m["recall"], "flagged": int(flags.sum())}
        curve.append(row)
        if m["f1"] > best["f1"]:
            best = {"n": N, "f1": m["f1"],
                    "precision": m["precision"], "recall": m["recall"]}
    return best, curve


# --------------------------- 평가지표 -----------------------------
def evaluate(labels, flags, point_adjust=False, events=None):
    n = len(labels)
    pred = np.array(flags, dtype=np.int8).copy()
    if point_adjust and events:
        for ev in events:
            seg = slice(ev["pos"], min(n, ev["pos"] + ev["len"]))
            if pred[seg].any():
                pred[seg] = 1
    tp = int(np.sum((labels == 1) & (pred == 1)))
    fp = int(np.sum((labels == 0) & (pred == 1)))
    fn = int(np.sum((labels == 1) & (pred == 0)))
    tn = int(np.sum((labels == 0) & (pred == 0)))
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": prec, "recall": rec, "f1": f1}


def affiliation_metrics(labels, flags, scale=20.0):
    """Huet et al. 2022 — 예측·정답 이벤트 간 시간거리 기반. 파라미터 없음."""
    n = len(labels)
    gt = np.where(labels == 1)[0]
    pred = np.where(np.array(flags) == 1)[0]
    if len(gt) == 0 or len(pred) == 0:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}

    def nearest(idx, arr):
        return np.min(np.abs(arr - idx))

    p = np.mean([1 / (1 + nearest(x, gt) / n * scale) for x in pred])
    r = np.mean([1 / (1 + nearest(x, pred) / n * scale) for x in gt])
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": float(p), "recall": float(r), "f1": float(f1)}


def evaluate_all(labels, flags, events):
    pw = evaluate(labels, flags, point_adjust=False)
    pa = evaluate(labels, flags, point_adjust=True, events=events)
    aff = affiliation_metrics(labels, flags)
    return {"pointwise": pw, "adjusted": pa, "affiliation": aff}


# ----------------------- 임계값 자동 스윕 -------------------------
def sweep_threshold(score, labels, events):
    """F1(point-adjusted) 최대 지점 탐색. 파일마다 임계값 재수립의 핵심."""
    best = {"th": 0.5, "f1": -1.0, "precision": 0.0, "recall": 0.0}
    roc = []
    for t in range(101):
        th = t / 100
        flags = (score >= th).astype(np.int8)
        m = evaluate(labels, flags, point_adjust=True, events=events)
        roc.append({"th": th, "precision": m["precision"],
                    "recall": m["recall"], "f1": m["f1"]})
        if m["f1"] > best["f1"]:
            best = {"th": th, "f1": m["f1"],
                    "precision": m["precision"], "recall": m["recall"]}
    return best, roc


def signature(s: np.ndarray) -> dict:
    return {"mean": float(s.mean()), "std": float(s.std()),
            "median": float(np.median(s)),
            "range": float(s.max() - s.min()), "n": int(len(s))}
