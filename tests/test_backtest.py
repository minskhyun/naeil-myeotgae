"""evaluate.py 테스트 (5-2): 신호 채택 규칙, 범위 보정, 전체 백테스트."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from contracts.schemas import BacktestResult
from ml.evaluate import (CALIB_TAUS, apply_calibration, below_rates, bootstrap_wape_change, check_calibration,
                         decide, fit_calibration, model_label, pick_combo, run_backtest, write_backtest)
from ml.features import load_sales, load_signals

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample" / "sinchon-a"


# ---------------------------------------------------------------- 신호 채택 규칙

def _s(wape, folds):
    return {"wape": wape, "wape_by_fold": folds}


@pytest.mark.parametrize("after, adopted, improved, words", [
    (_s(0.27, [0.25, 0.25, 0.25, 0.35]), True, 3, "사용함"),            # 전체 개선 + 4개 중 3개 개선
    (_s(0.29, [0.25, 0.35, 0.35, 0.25]), False, 2, "우연일 수 있어"),     # 전체는 개선, 하지만 2개 = 과반 아님
    (_s(0.31, [0.25, 0.35, 0.35, 0.35]), False, 1, "개선하지 못해"),      # 전체가 나빠짐
])
def test_decide_rules(after, adopted, improved, words):
    before = _s(0.30, [0.30, 0.30, 0.30, 0.30])
    d = decide("weather", ["temp_mean", "rain_mm"], before, after)
    assert d["adopted"] is adopted and d["folds_improved"] == improved and d["folds_total"] == 4
    assert words in d["reason"] and "날씨" in d["reason"]
    assert (d["wape_change_pct"] < 0) == (after["wape"] < 0.30)


def test_decide_without_data():
    d = decide("trend", [], None, None)
    assert d["adopted"] is False and d["folds_total"] == 0 and "자료가 아직 없어" in d["reason"]


def test_pick_combo():
    sc = lambda w, folds: dict(wape=w, wape_by_fold=folds)
    none = sc(0.30, [0.3, 0.3, 0.3, 0.3])
    scores = {(): none,
              ("weather",): sc(0.28, [0.27, 0.27, 0.29, 0.29]),            # 4개 중 2개만 개선 → 탈락
              ("events",): sc(0.27, [0.26, 0.26, 0.26, 0.31]),             # 3개 개선 → 통과
              ("weather", "events"): sc(0.25, [0.20, 0.20, 0.20, 0.40])}   # WAPE는 가장 낮지만 3개 개선 → 통과
    assert pick_combo(scores) == ["weather", "events"]                     # 통과한 것 중 WAPE 최저
    scores[("weather", "events")] = sc(0.20, [0.10, 0.10, 0.31, 0.31])     # 가장 낮아도 2개만 개선 → 탈락
    assert pick_combo(scores) == ["events"]
    assert pick_combo({(): none, ("weather",): sc(0.31, [0.31] * 4)}) == []   # 통과 조합 없음 → 신호 없이 M1


def test_model_label():
    assert model_label([]) == "M1"
    assert model_label(["weather"]) == "M2"
    assert model_label(["weather", "events"]) == "M3"
    assert model_label(["events"]) == "M3"                  # 날씨 없이 행사만 채택돼도 M3


# ---------------------------------------------------------------- 범위 보정

def _narrow_preds(n=2000, seed=0):
    """실제는 평균 20 근처로 넓게 흩어지는데, 예측 범위는 18~22로 너무 좁은 가짜 예측표."""
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        # 정수(포아송)면 같은 값이 많아 '실제 ≤ 예측' 비율이 계단처럼 튄다 → 연속값으로
        "qty": rng.normal(20, 5, n).clip(0), "sold_out": False, "base": 20.0,
        "p10": 18.0, "p50": 20.0, "pred": 20.0, "p60": 20.5, "p80": 21.5, "p90": 22.0,
    })


def test_calibration_makes_ranges_honest():
    preds = _narrow_preds()
    assert below_rates(preds)["p90"] < 0.75                 # 보정 전: p90 아래에 든 실제가 0.9보다 훨씬 적음
    shifts = fit_calibration(preds)
    assert shifts["p10"] < 0 < shifts["p90"]                # 아래 끝은 내리고 위 끝은 올림
    new = apply_calibration(_narrow_preds(seed=1), shifts)  # 새 데이터에 적용
    for col, tau in CALIB_TAUS.items():
        assert below_rates(new)[col] == pytest.approx(tau, abs=0.04)
    assert (new["p50"] == 20).all()                         # 예상 판매량은 그대로
    q = new[["p10", "p50", "p60", "p80", "p90"]].to_numpy()
    assert (np.diff(q, axis=1) >= 0).all() and (q >= 0).all()


def test_calibration_skipped_when_too_few_rows():
    assert fit_calibration(_narrow_preds(n=20)) is None


def _folds(offsets, n=500):
    """구간마다 실제 수준이 20+offset인 예측표들 (예측은 늘 20 근처로 같음)."""
    return pd.concat([_narrow_preds(n, seed=k).assign(fold=k, qty=lambda d, o=o: d["qty"] + o)
                      for k, o in enumerate(offsets)], ignore_index=True)


def test_check_calibration_adopts_when_error_is_stable():
    c = check_calibration(_folds([0, 0, 0, 0]))       # 매 구간 '범위가 좁다'는 같은 문제 → 보정이 통함
    assert c["adopted"] and c["folds_total"] == 3 and c["folds_improved"] >= 2


def test_check_calibration_rejects_when_error_flips():
    c = check_calibration(_folds([8, -8, 8, -8]))     # 높게·낮게 번갈아 빗나감 → 과거 오차로 옮기면 나빠짐
    assert not c["adopted"] and "쓰지 않음" in c["reason"]


def test_check_calibration_needs_two_folds():
    c = check_calibration(_folds([0]))
    assert not c["adopted"] and c["folds_total"] == 0 and "하나뿐" in c["reason"]


# ---------------------------------------------------------------- 블록 부트스트랩

def test_bootstrap_wape_change():
    days = pd.date_range("2026-01-01", periods=56)
    rng = np.random.default_rng(0)
    qty = rng.normal(50, 10, len(days))
    base = pd.DataFrame({"date": days, "menu": "빵", "qty": qty, "sold_out": False, "pred": qty + rng.normal(0, 10, len(days))})
    same = bootstrap_wape_change(base, base)
    assert same["change_pct"] == 0 and same["lo"] == 0 == same["hi"]
    better = base.assign(pred=qty + rng.normal(0, 3, len(days)))      # 오차가 훨씬 작은 모델
    b = bootstrap_wape_change(base, better)
    assert b["lo"] <= b["change_pct"] <= b["hi"] < 0                  # 구간 전체가 0보다 작음 = 우연이라 보기 어려움


# ---------------------------------------------------------------- 전체 백테스트

@pytest.fixture(scope="module")
def sample():
    return load_sales(SAMPLE / "sales.csv"), load_signals(SAMPLE / "signals.csv")


def test_run_backtest_full_sample(sample, tmp_path):
    sales, signals = sample
    bt = run_backtest(sales, signals, iterations=30)
    assert [d.signal_group for d in bt.decisions] == ["weather", "events", "trend", "special"]
    assert bt.decisions[2].folds_total == 0 == bt.decisions[3].folds_total   # 유행·기념일 신호는 가상 데이터에 없음
    assert [s.model for s in bt.cv_scores][:2] == ["M0", "M1"]
    assert len(bt.folds) == 4 and bt.test_period is not None
    assert [s.model for s in bt.test_scores] == ["M0", bt.chosen_model]
    assert bt.folds[-1][1] < bt.test_period[0]              # 검증은 모두 최종 테스트 전
    cal = bt.calibration
    assert cal.folds_total == 3 and cal.reason in bt.data_note
    if cal.adopted:                                         # 채택되면 이동량·테스트 효과가 기록됨
        assert cal.shifts and cal.test_coverage_after is not None
    else:                                                   # 아니면 비어 있음
        assert cal.shifts == {} and cal.test_coverage_after is None
    path = write_backtest(bt, tmp_path)
    assert BacktestResult.model_validate_json(path.read_text(encoding="utf-8")) == bt


def _first_days(sales, n):
    return sales[sales["date"] < sales["date"].min() + pd.Timedelta(days=n)]


def test_final_test_does_not_affect_choices(sample):
    """최종 테스트 기간의 판매를 10배로 바꿔도, 신호 채택·모델 선택·보정은 그대로여야 한다."""
    sales, signals = sample
    short = _first_days(sales, 35)
    a = run_backtest(short, signals, iterations=30)
    changed = short.copy()
    changed.loc[changed["date"] >= pd.Timestamp(a.test_period[0]), "qty"] *= 10
    b = run_backtest(changed, signals, iterations=30)
    assert a.decisions == b.decisions and a.chosen_model == b.chosen_model
    assert a.cv_scores == b.cv_scores
    assert (a.calibration.adopted, a.calibration.shifts) == (b.calibration.adopted, b.calibration.shifts)
    assert a.test_scores != b.test_scores                   # 테스트 점수만 달라짐


def test_short_data_without_test_period(sample):
    sales, signals = sample
    bt = run_backtest(_first_days(sales, 30), signals, iterations=30)
    assert bt.test_period is None and bt.test_scores == []
    assert "최종 테스트" in bt.data_note and "판매 기록 30일" in bt.data_note
