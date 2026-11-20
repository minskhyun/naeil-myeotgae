"""evaluate.py·calibration.py 테스트: 신호 채택 규칙, 범위 보정, 전체 백테스트."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from contracts.schemas import BacktestResult
from ml.calibration import CALIB_TAUS, apply_calibration, below_rates, check_calibration, fit_calibration
from ml.evaluate import FoldPlan, choose_signals, decide, model_label, pick_combo, run_backtest, write_backtest
from ml.metrics import bootstrap_wape_change
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


def test_pick_combo_needs_min_gain_and_prunes_freeloaders():
    sc = lambda w, folds: dict(wape=w, wape_by_fold=folds)
    none = sc(0.300, [0.30, 0.30, 0.30, 0.30])
    tiny = {(): none, ("special",): sc(0.294, [0.29, 0.29, 0.29, 0.31])}       # 2% 개선, 3구간 → 기준 미달
    assert pick_combo(tiny) == []
    scores = {(): none,
              ("weather",): sc(0.270, [0.26, 0.26, 0.26, 0.31]),              # 10% 개선
              ("special",): sc(0.296, [0.29, 0.29, 0.29, 0.31]),
              ("weather", "special"): sc(0.264, [0.25, 0.25, 0.25, 0.31])}    # 가장 낮지만 special을 빼도 2%만 차이
    assert pick_combo(scores) == ["weather"]                                   # 무임승차한 special은 빠짐


def test_decide_small_gain_reason():
    d = decide("special", ["special_day"], _s(0.300, [0.3] * 4), _s(0.294, [0.29, 0.29, 0.29, 0.31]))
    assert not d["adopted"] and "기준(3%)보다 작아" in d["reason"]


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
        "p10": 18.0, "p40": 19.5, "p50": 20.0, "pred": 20.0, "p60": 20.5, "p80": 21.5, "p90": 22.0,
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
    q = new[["p10", "p40", "p50", "p60", "p80", "p90"]].to_numpy()
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
    by_group = {d.signal_group: d for d in bt.decisions}
    assert list(by_group) == ["temp", "rain", "exam", "vacation", "festival", "nearby", "trend", "special"]
    assert by_group["trend"].folds_total == 0 == by_group["special"].folds_total   # 유행·기념일 신호는 가상 데이터에 없음
    assert by_group["temp"].folds_total == 4                                       # 기온은 평가됐다
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


def test_pick_combo_keeps_a_group_that_passes_alone():
    """날씨 혼자 기준을 통과하면, WAPE 1등 조합에 무임승차가 섞여 있어도 날씨는 채택된다 (11/19 실매장에서 나온 모양)."""
    sc = lambda w, folds: dict(wape=w, wape_by_fold=folds)                 # noqa: E731
    scores = {(): sc(0.4265, [0.376, 0.490]),
              ("weather",): sc(0.4057, [0.370, 0.450]),                    # −4.9%, 2구간 모두 개선 → 통과
              ("events",): sc(0.4151, [0.380, 0.455]),                     # 1구간만 개선 → 탈락
              ("special",): sc(0.4335, [0.380, 0.495]),
              ("weather", "events"): sc(0.4058, [0.378, 0.440]),           # 1구간만 개선 → 탈락
              ("weather", "special"): sc(0.4061, [0.371, 0.450]),
              ("events", "special"): sc(0.4157, [0.381, 0.456]),
              ("weather", "events", "special"): sc(0.4014, [0.372, 0.438])}   # WAPE 1등이지만 날씨 말고는 얹혀 가는 묶음
    assert pick_combo(scores) == ["weather"]


# ---------------------------------------------------------------- 두 단계 채택: 분야 → 분야 안의 묶음

class _FakeCV:
    """정해 둔 점수를 돌려주는 교차검증 (묶음 조합 → 점수). 어떤 조합을 물어봤는지 적어 둔다."""

    def __init__(self, table: dict):
        self.table, self.asked = table, []

    def key(self, groups) -> tuple:
        return tuple(groups)

    def run(self, groups):
        self.asked.append(tuple(groups))
        return None, self.table[tuple(groups)]


def _family_case():
    """기온(날씨 분야의 묶음 하나) + 시험기간·방학(학사일정·행사 분야의 묶음 둘)이 있는 매장."""
    days = pd.date_range("2026-01-01", periods=8)
    frame = pd.DataFrame({"date": days, "temp_diff": range(8), "exam_period": [0, 1] * 4, "vacation": [1, 0] * 4})
    plan = FoldPlan(folds=[(days[0], days[-1])], test=None, short=False, note="")
    sc = lambda wape, folds: {"wape": wape, "wape_by_fold": folds}      # noqa: E731
    return frame, plan, sc


def test_choose_signals_looks_inside_a_family():
    """분야 전체로는 기준에 못 미쳐도, 그 안에서 혼자 기준을 넘는 묶음은 쓴다 (방학은 듣고 시험기간은 안 듣는 가게)."""
    frame, plan, sc = _family_case()
    flat = sc(0.300, [0.30] * 4)
    cv = _FakeCV({
        (): flat, ("temp",): flat,
        ("exam", "vacation"): sc(0.295, [0.29, 0.29, 0.29, 0.31]),              # 분야 전체: 1.7% → 기준 미달
        ("temp", "exam", "vacation"): sc(0.295, [0.29, 0.29, 0.29, 0.31]),
        ("exam",): sc(0.302, [0.30, 0.30, 0.30, 0.31]),                         # 시험기간만: 도움 안 됨
        ("vacation",): sc(0.270, [0.26, 0.26, 0.26, 0.31]),                     # 방학만: 10%, 3구간 → 통과
    })
    adopted, decisions, n = choose_signals(frame, plan, cv)
    assert adopted == ["vacation"] and n == 6
    by_group = {d["signal_group"]: d for d in decisions}
    assert list(by_group) == ["temp", "rain", "exam", "vacation", "festival", "nearby", "trend", "special"]
    assert by_group["vacation"]["adopted"] and "사용함" in by_group["vacation"]["reason"] and "방학" in by_group["vacation"]["reason"]
    assert not by_group["exam"]["adopted"] and by_group["exam"]["folds_total"] == 4       # 방학 위에 얹어 봤지만 기준 미달
    assert not by_group["temp"]["adopted"] and by_group["rain"]["folds_total"] == 0       # 비는 자료가 없다


def test_choose_signals_keeps_a_family_that_only_works_together():
    """묶음 하나씩으로는 기준을 못 넘지만 분야 전체로는 넘으면, 전체를 그대로 쓰고 이유에 '함께'라고 적는다."""
    frame, plan, sc = _family_case()
    flat = sc(0.300, [0.30] * 4)
    both = sc(0.270, [0.26, 0.26, 0.26, 0.31])                                 # 분야 전체: 10% → 통과
    cv = _FakeCV({
        (): flat, ("temp",): flat, ("exam", "vacation"): both, ("temp", "exam", "vacation"): both,
        ("exam",): sc(0.293, [0.29, 0.29, 0.29, 0.31]),                         # 2.3% → 기준 미달
        ("vacation",): sc(0.292, [0.29, 0.29, 0.29, 0.31]),                     # 2.7% → 기준 미달
    })
    adopted, decisions, _ = choose_signals(frame, plan, cv)
    assert adopted == ["exam", "vacation"]
    for d in decisions:
        if d["signal_group"] in ("exam", "vacation"):
            assert d["adopted"] and "함께 사용함" in d["reason"] and "학사일정·행사" in d["reason"]


def test_choose_signals_drops_the_part_that_adds_nothing():
    """분야 전체가 통과했어도, 그 안에서 얹혀 가는 묶음은 덜어 낸다 (시험기간을 빼도 차이가 기준보다 작다)."""
    frame, plan, sc = _family_case()
    flat = sc(0.300, [0.30] * 4)
    cv = _FakeCV({
        (): flat, ("temp",): flat,
        ("exam", "vacation"): sc(0.268, [0.26, 0.26, 0.26, 0.31]), ("temp", "exam", "vacation"): sc(0.268, [0.26, 0.26, 0.26, 0.31]),
        ("exam",): sc(0.299, [0.30, 0.30, 0.30, 0.30]),
        ("vacation",): sc(0.270, [0.26, 0.26, 0.26, 0.31]),                     # 방학만으로 거의 다 얻는다
    })
    adopted, _, _ = choose_signals(frame, plan, cv)
    assert adopted == ["vacation"]


def test_family_names_still_work_as_groups():
    """예전 결과 파일에는 분야 이름(weather, events)이 적혀 있다 → 그 분야의 묶음 전부로 읽는다."""
    from ml.features import SIGNAL_GROUPS, SIGNAL_ORDER, expand, signals_in
    assert expand(["weather"]) == ["temp", "rain"] and expand(["events", "temp"]) == ["temp", "exam", "vacation", "festival", "nearby"]
    assert expand(list(SIGNAL_GROUPS)) == list(SIGNAL_GROUPS)
    frame = pd.DataFrame(columns=SIGNAL_ORDER)
    assert signals_in(["events", "weather"], frame) == SIGNAL_ORDER[:10]       # 묶음을 어떤 순서로 주든 열 순서는 같다
    with pytest.raises(KeyError):
        expand(["없는묶음"])
