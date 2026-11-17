"""범위 보정 (conformal): 예측 범위가 너무 좁거나 넓으면 검증 구간의 오차만큼 분위를 옮긴다.

    fit_calibration    검증 예측 → 분위마다 '평소 수준 대비' 이동량
    apply_calibration  이동량 적용 (p50은 그대로)
    check_calibration  보정을 쓸지 검증 구간 안에서만 판단 (신호 채택과 같은 생각: 과반 구간에서 좋아져야 씀)

입력 예측표에는 base 열(평소 수준, features.base_level)이 있어야 한다 (evaluate.cross_val_predict가 붙임).
"""
import numpy as np
import pandas as pd

from ml.metrics import pinball, scored

CALIB_TAUS = {"p10": 0.1, "p40": 0.4, "p60": 0.6, "p80": 0.8, "p90": 0.9}   # p50(예상 판매량)은 보정하지 않는다
MIN_CALIB_ROWS = 30


def fit_calibration(preds: pd.DataFrame) -> dict[str, float] | None:
    """교차검증 예측 → 분위마다 '평소 수준 대비' 이동량.  행이 너무 적으면 None.

    분위 tau 예측 q에 대해 (실제 − q) / 평소 수준 의 tau 분위수를 이동량으로 쓴다.
    → 이동 후에는 검증 기간에서 '실제 ≤ q'인 비율이 tau가 된다.
    비율 단위라서 하루 60개 메뉴와 10개 메뉴에 같은 기준을 쓸 수 있다 (CatBoost 목표와 같은 생각).
    """
    d = scored(preds)
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
    """이동량 적용: q' = q + 이동량 × 평소 수준.  p50은 그대로 두고 순서(p10 ≤ p40 ≤ p50 ≤ … ≤ p90)를 지킨다."""
    out = preds.copy()
    for col, s in shifts.items():
        out[col] = out[col] + s * out["base"]
    out["p40"] = np.minimum(out["p40"], out["p50"])
    out["p10"] = np.minimum(out["p10"], out["p40"]).clip(lower=0)
    out["p60"] = np.maximum(out["p60"], out["p50"])
    out["p80"] = np.maximum(out["p80"], out["p60"])
    out["p90"] = np.maximum(out["p90"], out["p80"])
    return out


def quantile_loss(preds: pd.DataFrame) -> float:
    """보정 대상 분위(p10·p40·p60·p80·p90)의 pinball loss 평균. 범위가 '정직하고 좁을수록' 작다."""
    d = scored(preds)
    return float(np.mean([pinball(d["qty"], d[c], tau) for c, tau in CALIB_TAUS.items()]))


def check_calibration(cv_preds: pd.DataFrame) -> dict:
    """보정을 쓸지 검증 구간 안에서만 판단한다 (최종 테스트는 보지 않음).

    구간 k마다: 구간 0…k−1의 오차로 이동량을 정해 → 구간 k에 적용 → pinball이 줄었나?
    채택 조건: 전체 pinball이 줄고, 검사한 구간의 과반에서 줄었을 때.
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
    d = scored(preds)
    return {c: round(float((d["qty"] <= d[c]).mean()), 3) for c in CALIB_TAUS}
