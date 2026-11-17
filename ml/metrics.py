"""예측이 얼마나 맞았는지 재는 지표.

입력은 모두 '예측표': 한 행 = (날짜, 메뉴) 하나, 열 = qty(실제), pred·p10…p90(예측), sold_out, fold.
(evaluate.cross_val_predict가 만든다)

    wape      Σ|실제−예측| / Σ실제      ← 메인 지표. '판매량의 몇 %를 틀렸나'
    coverage  실제가 [p10, p90] 안에 든 비율 ← 화면의 '예상 범위 안에 든 비율' (목표 0.8)
"""
import numpy as np
import pandas as pd


def wape(y, p) -> float:
    """Σ|실제−예측| / Σ실제.  '전체 판매량 대비 몇 %를 틀렸나'. 메인 지표."""
    y, p = np.asarray(y, float), np.asarray(p, float)
    return float(np.abs(y - p).sum() / y.sum()) if y.sum() > 0 else float("nan")


def mae(y, p) -> float:
    """하루·메뉴당 평균 몇 개 틀렸나."""
    return float(np.mean(np.abs(np.asarray(y, float) - np.asarray(p, float))))


def bias(y, p) -> float:
    """Σ(예측−실제) / Σ실제.  +면 많이 예측하는 경향(폐기 쪽), −면 적게 예측하는 경향(품절 쪽)."""
    y, p = np.asarray(y, float), np.asarray(p, float)
    return float((p - y).sum() / y.sum()) if y.sum() > 0 else float("nan")


def pinball(y, q, tau: float) -> float:
    """분위 tau 예측 q의 pinball loss 평균.  실제가 위면 tau×차이, 아래면 (1−tau)×차이."""
    diff = np.asarray(y, float) - np.asarray(q, float)
    return float(np.mean(np.maximum(tau * diff, (tau - 1) * diff)))


def coverage(y, lo, hi) -> float:
    """실제값이 [lo, hi] 안에 든 비율.  [p10, p90]이면 0.8 근처가 이상적."""
    y = np.asarray(y, float)
    return float(np.mean((y >= np.asarray(lo, float)) & (y <= np.asarray(hi, float))))


def scored(preds: pd.DataFrame) -> pd.DataFrame:
    """채점에 쓰는 행만.  ★ 품절일은 실제값이 수요의 하한일 뿐이라 뺀다."""
    return preds[~preds["sold_out"].astype(bool)]


def score(preds: pd.DataFrame, model: str) -> dict:
    """예측표 → 점수 한 줄 (contracts.ModelScore 형식의 dict)."""
    d = scored(preds)
    y = d["qty"]
    return dict(
        model=model, wape=wape(y, d["pred"]), mae=mae(y, d["pred"]), bias=bias(y, d["pred"]),
        pinball_p10=pinball(y, d["p10"], 0.1), pinball_p90=pinball(y, d["p90"], 0.9),
        coverage_80=coverage(y, d["p10"], d["p90"]), n=len(d),
        wape_by_fold=[wape(g["qty"], g["pred"]) for _, g in d.groupby("fold")],
    )


def bootstrap_wape_change(base: pd.DataFrame, other: pd.DataFrame, block: int = 7, n_boot: int = 1000,
                          seed: int = 0) -> dict:
    """other의 WAPE가 base보다 몇 % 다른가 + 95% 구간 (이동 블록 부트스트랩).

    날짜를 하나씩이 아니라 '이어진 7일 묶음'으로 다시 뽑는다. 이어진 날들은 비슷하게 틀리는 경향이
    있어서, 하루씩 뽑으면 구간이 실제보다 좁게(자신 있게) 나온다.
    """
    keys = ["date", "menu"]
    d = scored(base)[keys + ["qty", "pred"]].merge(scored(other)[keys + ["pred"]], on=keys, suffixes=("_a", "_b"))
    day = d.assign(ea=(d["qty"] - d["pred_a"]).abs(), eb=(d["qty"] - d["pred_b"]).abs()).groupby("date")[["qty", "ea", "eb"]].sum()
    v = day.to_numpy()                                             # 날짜별 [실제 합, base 오차 합, other 오차 합]
    change = lambda s: (s[2] / s[0] - s[1] / s[0]) / (s[1] / s[0]) * 100

    rng = np.random.default_rng(seed)
    n, block = len(v), min(block, len(v))
    starts = rng.integers(0, n - block + 1, size=(n_boot, -(-n // block)))   # 묶음 시작 위치 (올림 나눗셈)
    idx = (starts[..., None] + np.arange(block)).reshape(n_boot, -1)[:, :n]
    boots = np.array([change(v[i].sum(axis=0)) for i in idx])
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return dict(change_pct=round(float(change(v.sum(axis=0))), 1), lo=round(float(lo), 1), hi=round(float(hi), 1))
