"""metrics.py·evaluate.py 테스트: 지표 손 계산, 검증 구간 나누기, 교차검증의 시점."""
from pathlib import Path

import pandas as pd
import pytest

from ml.evaluate import cross_val_predict, plan_folds
from ml.metrics import bias, coverage, mae, pinball, score, wape
from ml.features import build_frame, load_sales

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample" / "sinchon-a"


# ---------------------------------------------------------------- 지표 (손 계산)

def test_metrics_by_hand():
    y, p = [50, 1, 50], [55, 2, 50]
    assert wape(y, p) == pytest.approx(6 / 101)               # TASKS.md §4의 지표 테스트
    assert mae(y, p) == pytest.approx(2)
    assert bias(y, p) == pytest.approx(6 / 101)               # 많이 예측 → +
    assert bias([10], [8]) == pytest.approx(-0.2)             # 적게 예측 → −


def test_pinball_by_hand():
    # 지난번 설명의 예: 실제 50개
    assert pinball([50], [44], 0.1) == pytest.approx(0.6)     # p10을 6 낮게: 0.1 × 6
    assert pinball([50], [56], 0.1) == pytest.approx(5.4)     # p10을 6 높게: 0.9 × 6
    assert pinball([50], [68], 0.9) == pytest.approx(1.8)     # p90을 18 높게: 0.1 × 18
    assert pinball([50], [45], 0.9) == pytest.approx(4.5)     # p90을 5 낮게: 0.9 × 5
    assert pinball([50, 40], [45, 45], 0.5) == pytest.approx(0.5 * mae([50, 40], [45, 45]))  # τ=0.5면 MAE의 절반


def test_coverage():
    assert coverage([5, 10, 15, 20], [0, 0, 0, 0], [10, 10, 10, 10]) == 0.5   # 경계값(10)은 안에 든 것으로


def test_score_excludes_sold_out_days():
    preds = pd.DataFrame({"qty": [10, 80], "sold_out": [False, True], "pred": [12, 50],
                          "p10": [8, 40], "p90": [15, 60], "fold": [0, 0]})
    s = score(preds, "M1")
    assert s["n"] == 1 and s["wape"] == pytest.approx(0.2)    # 품절일(80개)은 채점에서 빠짐


# ---------------------------------------------------------------- 검증 구간 나누기

def _days(n, start="2026-01-01"):
    return pd.date_range(start, periods=n)


def test_plan_normal_one_year():
    p = plan_folds(_days(365))
    assert not p.short and len(p.folds) == 4
    assert p.test == (pd.Timestamp("2026-12-04"), pd.Timestamp("2026-12-31"))          # 마지막 28일
    assert p.folds[-1][1] == p.test[0] - pd.Timedelta(days=1)                           # 테스트 바로 앞까지 검증
    for (s1, e1), (s2, _) in zip(p.folds, p.folds[1:]):
        assert e1 + pd.Timedelta(days=1) == s2                                          # 구간이 빈틈·겹침 없이 이어짐
    assert all((e - s).days + 1 == 28 for s, e in p.folds)


@pytest.mark.parametrize("n, n_folds, has_test", [(35, 2, True), (30, 2, False), (22, 1, False)])
def test_plan_short_data_shrinks(n, n_folds, has_test):
    p = plan_folds(_days(n))
    assert p.short and len(p.folds) == n_folds and (p.test is not None) == has_test
    assert f"판매 기록 {n}일" in p.note
    if not has_test:
        assert "최종 테스트" in p.note


def test_plan_too_short_raises():
    with pytest.raises(ValueError, match="검증할 수 없습니다"):
        plan_folds(_days(15))


# ---------------------------------------------------------------- 교차검증

def test_cross_val_predict_never_trains_on_the_future():
    frame = build_frame(load_sales(SAMPLE / "sales.csv"))
    plan = plan_folds(frame["date"])
    preds = cross_val_predict(frame, "M1", plan.folds, iterations=10)
    for k, (start, end) in enumerate(plan.folds):
        part = preds[preds["fold"] == k]
        assert part["train_last"].max() < start                                         # 학습은 구간 시작 전까지만
        assert part["date"].between(start, end).all()
    assert len(preds) == frame[frame["date"].between(plan.folds[0][0], plan.folds[-1][1])]["qty"].notna().sum()
