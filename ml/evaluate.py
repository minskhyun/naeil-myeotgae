"""모델 평가: 지표 → 시간순 교차검증 → 신호 조합 선택(모든 조합 비교) → 범위 보정 → 최종 테스트 → backtest.json.

시간순 교차검증 (rolling origin: 학습 기간을 늘려 가며)
    |------ 학습 ------|-검증1-|-검증2-|-검증3-|-검증4-|== 최종 테스트 ==|
    검증 k: 그 구간 시작 전 데이터 전부로 새 모델을 학습 → 구간 안의 각 날짜를 '하루 앞' 예측
            (구간 안에서는 재학습하지 않는다. 변수는 features.py가 이미 날마다 최신 판매로 계산해 둠)
    최종 테스트: 모델·신호·보정을 모두 정한 뒤 딱 한 번. 그 결과를 보고 아무것도 바꾸지 않는다.

실행:  python -m ml.evaluate [매장 폴더]      (기본: data/sample/sinchon-a)
       → data/artifacts/{store_id}/backtest.json
"""
import datetime as dt
import json
import sys
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

from contracts.schemas import BacktestResult
from ml.features import (DEFAULT_CLOSE_TIME, FEATURE_SETS, SIGNAL_GROUPS, available_signals, build_frame,
                         load_sales, load_signals, signals_in)
from ml.models import base_level, make_model

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "data" / "artifacts"


# ---------------------------------------------------------------- 지표

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


def _scored(preds: pd.DataFrame) -> pd.DataFrame:
    """채점에 쓰는 행만.  ★ 품절일은 실제값이 수요의 하한일 뿐이라 뺀다."""
    return preds[~preds["sold_out"].astype(bool)]


def score(preds: pd.DataFrame, model: str) -> dict:
    """교차검증 예측표 → ModelScore 형식의 dict."""
    d = _scored(preds)
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
    d = _scored(base)[keys + ["qty", "pred"]].merge(_scored(other)[keys + ["pred"]], on=keys, suffixes=("_a", "_b"))
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


# ---------------------------------------------------------------- 검증 구간 나누기

@dataclass
class FoldPlan:
    folds: list[tuple[pd.Timestamp, pd.Timestamp]]   # 검증 구간들 (시작, 끝) — 끝 날짜 포함
    test: tuple[pd.Timestamp, pd.Timestamp] | None    # 최종 테스트 구간 (없을 수 있음)
    n_sales_days: int                                 # 판매 기록이 있는 날 수
    short: bool                                       # 짧은 데이터 모드인가
    note: str                                         # data_note에 들어갈 설명


SHORT_DATA_DAYS = 120
# (최종 테스트 일수, 검증 구간 일수, 검증 구간 개수, 최소 학습 일수) — 앞에서부터 들어맞는 첫 설정을 쓴다
PLANS_NORMAL = [(28, 28, 4, 56)]
PLANS_SHORT = [(7, 7, 2, 14), (0, 7, 2, 14), (0, 7, 1, 14)]


def plan_folds(dates) -> FoldPlan:
    """판매 날짜들 → 검증 구간·최종 테스트 구간.  데이터 길이에 맞춰 자동으로 줄인다."""
    dates = pd.DatetimeIndex(pd.to_datetime(pd.Series(dates).unique())).sort_values()
    first, last = dates[0], dates[-1]
    span = (last - first).days + 1                    # 달력 일수 (휴무일 포함)
    n_days = len(dates)
    short = n_days < SHORT_DATA_DAYS

    for test_days, fold_days, n_folds, min_train in (PLANS_SHORT if short else PLANS_NORMAL):
        if span < min_train + fold_days * n_folds + test_days:
            continue
        day = pd.Timedelta(days=1)
        test = (last - (test_days - 1) * day, last) if test_days else None
        end = (test[0] - day) if test else last       # 마지막 검증 구간의 끝
        folds = []
        for _ in range(n_folds):
            start = end - (fold_days - 1) * day
            folds.insert(0, (start, end))             # 앞쪽(과거)부터 순서대로 놓이게
            end = start - day

        parts = [f"판매 기록 {n_days}일"]
        if short:
            parts.append(f"검증 {n_folds}개 구간×{fold_days}일로 짧아 결과의 변동이 큼")
        if test is None:
            parts.append("최종 테스트 기간을 따로 둘 만큼 길지 않아 검증 구간 결과만 보고함")
        return FoldPlan(folds, test, n_days, short, ". ".join(parts))

    raise ValueError(f"판매 기록이 {n_days}일(달력 {span}일)뿐이라 검증할 수 없습니다. 최소 21일이 필요합니다.")


# ---------------------------------------------------------------- 교차검증

KEEP_COLS = ["store_id", "date", "menu", "qty", "sold_out"]


def cross_val_predict(frame: pd.DataFrame, model_name: str, folds, **model_kwargs) -> pd.DataFrame:
    """검증 구간마다 '그 전 데이터로만' 학습해서 구간 안을 예측한다.
    최종 테스트도 같은 함수에 구간 하나([test])를 넣어 계산한다.

    반환: 검증 행마다 실제값 + 예측(p10…p90, pred) + fold 번호 + train_last(학습에 쓴 마지막 날짜)
          + base(평소 수준, 범위 보정에 씀).  train_last < 구간 시작일 이어야 한다 (테스트로 확인).
    """
    labeled = frame[frame["qty"].notna()]
    out = []
    for k, (start, end) in enumerate(folds):
        train = labeled[labeled["date"] < start]
        valid = labeled[(labeled["date"] >= start) & (labeled["date"] <= end)]
        model = make_model(model_name, **model_kwargs).fit(train)
        pred = model.predict(valid)
        out.append(valid[KEEP_COLS].join(pred).assign(fold=k, train_last=train["date"].max(),
                                                      base=base_level(valid)))
    return pd.concat(out, ignore_index=True)


# ---------------------------------------------------------------- 신호 채택

GROUP_LABELS = {"weather": "날씨", "events": "학사일정·행사", "trend": "유행", "special": "기념일"}


def model_label(groups) -> str:
    """채택된 신호 묶음 → 모델 이름.  없음=M1, 날씨만=M2, 학사일정·행사·유행 중 하나라도=M3.
    (날씨는 빠지고 행사만 채택돼도 M3라고 부른다. 실제로 쓴 신호는 signals_used·decisions에 있다.)"""
    groups = set(groups)
    if not groups:
        return "M1"
    return "M2" if groups <= {"weather"} else "M3"


def beats(after: dict, before: dict) -> tuple[bool, int, float]:
    """after가 before보다 나은가 → (통과 여부, 개선된 구간 수, 전체 WAPE 변화 %).
    통과 조건 (TASKS.md §8): 전체 WAPE가 줄고, 검증 구간의 과반에서 WAPE가 줄었을 때."""
    improved = sum(a < b for a, b in zip(after["wape_by_fold"], before["wape_by_fold"]))
    change = (after["wape"] - before["wape"]) / before["wape"] * 100
    return change < 0 and improved > len(before["wape_by_fold"]) / 2, improved, change


def pick_combo(scores: dict[tuple, dict]) -> list[str]:
    """{조합(묶음 이름 튜플): 교차검증 점수} → 고른 조합.  () = 신호 없음(M1).
    신호 없음보다 beats()를 통과한 조합 중 전체 WAPE가 가장 낮은 것. 하나도 없으면 [] (신호 없이 M1)."""
    passing = [c for c in scores if c and beats(scores[c], scores[()])[0]]
    return list(min(passing, key=lambda c: scores[c]["wape"])) if passing else []


def decide(group: str, signals: list[str], before: dict | None, after: dict | None,
           adopted: bool | None = None) -> dict:
    """신호 묶음 하나를 넣기 전(before)·후(after)의 교차검증 점수 → SignalDecision 형식의 dict.

    adopted를 주지 않으면 beats()의 조건으로 정한다. 조합 선택(run_backtest)은 채택 여부를 정해서 넘기고,
    이 함수는 그 묶음을 넣었을 때와 뺐을 때의 차이로 이유 문장만 만든다.
    """
    label = GROUP_LABELS.get(group, group)
    if after is None:                                  # 이 매장에 그 신호 자료가 없음
        return dict(signal_group=group, signals=[], adopted=False, wape_change_pct=0.0,
                    folds_improved=0, folds_total=0, reason=f"{label} 신호 자료가 아직 없어 평가하지 못함")

    total = len(before["wape_by_fold"])
    passed, improved, change = beats(after, before)
    adopted = passed if adopted is None else adopted

    if adopted:
        reason = f"{label} 신호를 넣으니 검증 {total}개 구간 중 {improved}개에서 오차가 줄어 사용함 (전체 오차 {-change:.1f}% 감소)"
    elif change >= 0:
        reason = f"{label} 신호는 이 매장 판매 예측을 개선하지 못해 쓰지 않음 ({total}개 구간 중 {improved}개만 개선)"
    else:
        reason = (f"{label} 신호는 전체 오차를 {-change:.1f}% 줄였지만 {total}개 구간 중 {improved}개에서만 "
                  f"개선돼 우연일 수 있어 쓰지 않음")
    return dict(signal_group=group, signals=list(signals), adopted=adopted, wape_change_pct=round(change, 2),
                folds_improved=improved, folds_total=total, reason=reason)


# ---------------------------------------------------------------- 범위 보정

CALIB_TAUS = {"p10": 0.1, "p40": 0.4, "p60": 0.6, "p80": 0.8, "p90": 0.9}   # p50(예상 판매량)은 보정하지 않는다
MIN_CALIB_ROWS = 30


def fit_calibration(preds: pd.DataFrame) -> dict[str, float] | None:
    """교차검증 예측 → 분위마다 '평소 수준 대비' 이동량.  행이 너무 적으면 None.

    분위 tau 예측 q에 대해 (실제 − q) / 평소 수준 의 tau 분위수를 이동량으로 쓴다.
    → 이동 후에는 검증 기간에서 '실제 ≤ q'인 비율이 tau가 된다.
    비율 단위라서 하루 60개 메뉴와 10개 메뉴에 같은 기준을 쓸 수 있다 (CatBoost 목표와 같은 생각).
    """
    d = _scored(preds)
    if len(d) < MIN_CALIB_ROWS:
        return None
    ratio = d["qty"] / d["base"]
    shifts = {}
    for col, tau in CALIB_TAUS.items():
        resid = ratio - d[col] / d["base"]
        # 위쪽 분위는 조금 넉넉하게(higher), 아래쪽은 조금 낮게(lower) 잡는다
        shifts[col] = float(np.quantile(resid, tau, method="higher" if tau > 0.5 else "lower"))
    return shifts


def apply_calibration(preds: pd.DataFrame, shifts: dict[str, float]) -> pd.DataFrame:
    """이동량 적용: q' = q + 이동량 × 평소 수준.  p50은 그대로 두고 순서(p10 ≤ p50 ≤ … ≤ p90)를 지킨다."""
    out = preds.copy()
    for col, s in shifts.items():
        out[col] = out[col] + s * out["base"]
    if "p40" in out:                                   # 예전 결과(p40 없음)도 읽을 수 있게
        out["p40"] = np.minimum(out["p40"], out["p50"])
        out["p10"] = np.minimum(out["p10"], out["p40"])
    out["p10"] = np.minimum(out["p10"], out["p50"]).clip(lower=0)
    out["p60"] = np.maximum(out["p60"], out["p50"])
    out["p80"] = np.maximum(out["p80"], out["p60"])
    out["p90"] = np.maximum(out["p90"], out["p80"])
    return out


def quantile_loss(preds: pd.DataFrame) -> float:
    """보정 대상 분위(p10·p40·p60·p80·p90)의 pinball loss 평균. 범위가 '정직하고 좁을수록' 작다."""
    d = _scored(preds)
    return float(np.mean([pinball(d["qty"], d[c], tau) for c, tau in CALIB_TAUS.items()]))


def check_calibration(cv_preds: pd.DataFrame) -> dict:
    """보정을 쓸지 검증 구간 안에서만 판단한다 (최종 테스트는 보지 않음).

    구간 k마다: 구간 0…k−1의 오차로 이동량을 정해 → 구간 k에 적용 → pinball이 줄었나?
    채택 조건은 신호와 같다: 전체 pinball이 줄고, 검사한 구간의 과반에서 줄었을 때.
    """
    folds = sorted(cv_preds["fold"].unique())
    raw, cal, improved = [], [], 0
    for k in folds[1:]:
        shifts = fit_calibration(cv_preds[cv_preds["fold"] < k])
        if shifts is None:
            continue
        nxt = cv_preds[cv_preds["fold"] == k]
        fixed = apply_calibration(nxt, shifts)
        improved += quantile_loss(fixed) < quantile_loss(nxt)
        raw.append(nxt)
        cal.append(fixed)

    total = len(raw)
    if total == 0:
        why = "검증 구간이 하나뿐이라" if len(folds) < 2 else f"검증 행이 {MIN_CALIB_ROWS}개 미만이라"
        return dict(adopted=False, folds_improved=0, folds_total=0,
                    reason=f"{why} 범위 보정의 효과를 확인할 수 없어 쓰지 않음")
    before, after = quantile_loss(pd.concat(raw)), quantile_loss(pd.concat(cal))
    adopted = after < before and improved > total / 2
    if adopted:
        reason = f"범위 보정이 검사한 {total}개 구간 중 {improved}개에서 예측 범위를 개선해 사용함"
    elif improved <= total / 2:
        reason = f"범위 보정이 검사한 {total}개 구간 중 {improved}개만 개선해 쓰지 않음"
    else:
        reason = f"범위 보정이 {total}개 구간 중 {improved}개에서 개선됐지만 전체로는 나빠져 쓰지 않음"
    return dict(adopted=adopted, folds_improved=improved, folds_total=total, reason=reason)


def below_rates(preds: pd.DataFrame) -> dict[str, float]:
    """분위마다 '실제 ≤ 예측' 비율.  p10이면 0.1, p80이면 0.8에 가까울수록 범위가 정직하다."""
    d = _scored(preds)
    return {c: round(float((d["qty"] <= d[c]).mean()), 3) for c in CALIB_TAUS}


# ---------------------------------------------------------------- 전체 백테스트

def run_backtest(sales: pd.DataFrame, signals: pd.DataFrame | None = None,
                 close_time: str = DEFAULT_CLOSE_TIME, **model_kwargs) -> BacktestResult:
    """매장 하나의 판매(+신호) → BacktestResult.  model_kwargs는 테스트용 (예: iterations=30)."""
    store_ids = sales["store_id"].unique()
    if len(store_ids) != 1:
        raise ValueError(f"매장 하나씩 평가합니다. 받은 매장: {list(store_ids)}")
    store_id = str(store_ids[0])

    names = []
    if signals is not None:
        signals = signals[signals["store_id"] == store_id]
        names = available_signals(SIGNAL_GROUPS, signals)
    frame = build_frame(sales, signals, names, close_time=close_time)
    plan = plan_folds(frame.loc[frame["qty"].notna(), "date"])

    # 같은 신호 조합은 한 번만 교차검증한다 (조합 = 실제로 쓰는 신호 이름들)
    cache: dict[tuple, tuple[pd.DataFrame, dict]] = {}

    def cv(groups, label):
        key = tuple(signals_in(groups, frame))
        if key not in cache:
            preds = cross_val_predict(frame, label, plan.folds, groups=list(groups), **model_kwargs)
            cache[key] = (preds, score(preds, label))
        return key, cache[key]

    # 1) 신호 조합 고르기: 자료가 있는 묶음의 모든 조합(묶음 n개면 2^n가지)을 같은 검증 구간에서 비교한다.
    #    신호 없음(M1)보다 전체 WAPE가 낮고 검증 구간 과반에서 나은 조합 중 WAPE가 가장 낮은 것을 고른다.
    #    (통과하는 조합이 없으면 신호 없이 M1. 1등만 고르면 우연히 좋게 나온 조합을 고를 위험이 커서 이 조건을 둔다)
    present = [g for g in SIGNAL_GROUPS if signals_in([g], frame)]
    combos = [list(c) for r in range(len(present) + 1) for c in combinations(present, r)]
    scores = {tuple(c): cv(c, model_label(c))[1][1] for c in combos}
    adopted = pick_combo(scores)

    # 묶음마다 이유: 고른 조합에서 그 묶음을 넣었을 때 vs 뺐을 때
    decisions = []
    for group in SIGNAL_GROUPS:
        if group not in present:
            decisions.append(decide(group, [], None, None))
            continue
        without = tuple(g for g in adopted if g != group)
        with_ = tuple(g for g in present if g in adopted or g == group)
        decisions.append(decide(group, signals_in([group], frame), scores[without], scores[with_],
                                adopted=group in adopted))
    chosen = model_label(adopted)
    chosen_key, (chosen_cv, _) = cv(adopted, chosen)

    # 2) 화면용 비교표: M0 + 팀 기본 정의의 M1·M2·M3 (+ 채택 조합이 그중에 없으면 따로 한 줄)
    cv_m0 = cross_val_predict(frame, "M0", plan.folds)
    cv_scores, seen = [score(cv_m0, "M0")], set()
    for name in ["M1", "M2", "M3"]:
        key, (preds, _) = cv(FEATURE_SETS[name], name)
        if key not in seen:                            # 신호 자료가 없어 앞 모델과 같으면 생략
            seen.add(key)
            cv_scores.append(score(preds, name))
    if chosen_key not in seen:
        cv_scores.append(score(chosen_cv, f"{chosen}(채택 신호만)"))

    # 3) 범위 보정: 검증 구간 안에서 효과를 확인한 뒤, 채택되면 검증 구간 전체의 오차로 이동량을 정한다
    check = check_calibration(chosen_cv)
    shifts = fit_calibration(chosen_cv) if check["adopted"] else None
    calibration = dict(method="conformal-ratio", **check, n_rows=len(_scored(chosen_cv)),
                       shifts={k: round(v, 4) for k, v in shifts.items()} if shifts else {})

    # 4) 최종 테스트: 위에서 모두 정한 뒤 딱 한 번. M0 vs 채택 모델(보정 적용)
    test_scores, n_sold_out = [], int(cv_m0["sold_out"].astype(bool).sum())
    if plan.test is not None:
        t_m0 = cross_val_predict(frame, "M0", [plan.test])
        t_raw = cross_val_predict(frame, chosen, [plan.test], groups=adopted, **model_kwargs)
        t_final = apply_calibration(t_raw, shifts) if shifts is not None else t_raw
        test_scores = [score(t_m0, "M0"), score(t_final, chosen)]
        n_sold_out += int(t_m0["sold_out"].astype(bool).sum())
        if shifts is not None:
            d_raw, d_cal = _scored(t_raw), _scored(t_final)
            calibration.update(
                test_coverage_before=round(coverage(d_raw["qty"], d_raw["p10"], d_raw["p90"]), 3),
                test_coverage_after=round(coverage(d_cal["qty"], d_cal["p10"], d_cal["p90"]), 3),
                test_below_before=below_rates(t_raw), test_below_after=below_rates(t_final))

    # 5) data_note: 화면과 발표에서 그대로 밝힐 설명
    notes = [plan.note]
    if len(combos) > 1:
        picked = ", ".join(GROUP_LABELS.get(g, g) for g in adopted) or "신호 없음"
        notes.append(f"신호 조합 {len(combos)}가지를 모두 비교해 '{picked}' 선택")
    b = bootstrap_wape_change(cv_m0, chosen_cv)
    if cv_m0["date"].nunique() < 4 * 7:                   # 7일 묶음이 4개도 안 되면 구간을 믿기 어렵다
        notes.append(f"검증 구간에서 {chosen}의 오차가 M0 대비 {b['change_pct']:+.1f}% (기간이 짧아 우연 여부는 판단하지 않음)")
    else:
        sure = "우연이라 보기 어려움" if b["hi"] < 0 else "우연일 수 있음"
        notes.append(f"검증 구간에서 {chosen}의 오차가 M0 대비 {b['change_pct']:+.1f}% "
                     f"(95% 구간 {b['lo']:+.1f}~{b['hi']:+.1f}%, {sure})")
    if n_sold_out:
        notes.append(f"품절로 실제 수요를 알 수 없는 {n_sold_out}개 행은 채점에서 뺌")
    notes.append(check["reason"])

    day = lambda t: pd.Timestamp(t).date()
    return BacktestResult(
        store_id=store_id, generated_at=dt.datetime.now().replace(microsecond=0),
        folds=[(day(s), day(e)) for s, e in plan.folds],
        test_period=(day(plan.test[0]), day(plan.test[1])) if plan.test else None,
        cv_scores=cv_scores, decisions=decisions, chosen_model=chosen, test_scores=test_scores,
        data_note=". ".join(notes), calibration=calibration,
    )


def write_backtest(result: BacktestResult, out_root: Path = ARTIFACTS) -> Path:
    path = Path(out_root) / result.store_id / "backtest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return path


def main(store_dir: str | None = None) -> Path:
    sys.stdout.reconfigure(encoding="utf-8")          # 윈도우에서 출력을 파이프로 넘길 때 한글이 깨지지 않게
    store_dir = Path(store_dir or ROOT / "data" / "sample" / "sinchon-a")
    info = json.loads((store_dir / "store.json").read_text(encoding="utf-8"))
    sales = load_sales(store_dir / "sales.csv")
    signals = load_signals(store_dir / "signals.csv") if (store_dir / "signals.csv").exists() else None
    result = run_backtest(sales, signals, close_time=info.get("close_time", DEFAULT_CLOSE_TIME))
    path = write_backtest(result)

    print(f"[{result.store_id}] 선택 모델: {result.chosen_model}")
    for d in result.decisions:
        print("  -", d.reason)
    for s in result.test_scores:
        print(f"  최종 테스트 {s.model}: WAPE {s.wape:.3f}, 범위 적중 {s.coverage_80:.2f}")
    print("  메모:", result.data_note)
    print("  저장:", path)
    return path


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
