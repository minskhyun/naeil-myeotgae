"""models.py 테스트: M0 손 계산, CatBoost 출력 모양·분위 순서·품절 제외."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ml.features import SIGNAL_GROUPS, build_frame, load_sales, load_signals
from ml.models import Q_COLS, make_model

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample" / "sinchon-a"
ALL_SIGNALS = [n for names in SIGNAL_GROUPS.values() for n in names]


@pytest.fixture(scope="module")
def frame():
    with pytest.warns(UserWarning):     # trend 신호가 아직 없다는 경고
        return build_frame(load_sales(SAMPLE / "sales.csv"), load_signals(SAMPLE / "signals.csv"), ALL_SIGNALS)


def test_m0_by_hand():
    f = pd.DataFrame({
        "lag_7":          [50.0, np.nan, np.nan, np.nan],
        "same_wd_mean_4": [45.0, 40.0,   np.nan, np.nan],
        "same_wd_min_4":  [30.0, 20.0,   np.nan, np.nan],
        "same_wd_max_4":  [70.0, 60.0,   np.nan, np.nan],
        "mean_7":         [48.0, 44.0,   33.0,   np.nan],
    })
    out = make_model("M0").fit(f).predict(f)
    assert out["pred"].tolist() == [50, 40, 33, 0]        # lag_7 → 4주 평균 → 7일 평균 → 0
    assert out.loc[0, ["p10", "p40", "p60", "p80", "p90"]].tolist() == [30, 45, 55, 65, 70]
    assert (out.loc[2, Q_COLS] == 33).all()               # 같은 요일 기록이 없으면 범위 없이 한 값


@pytest.mark.parametrize("name", ["M1", "M2", "M3"])
def test_catboost_output_shape_and_order(frame, name):
    train = frame[frame["date"] < "2026-09-01"]
    test = frame[frame["date"] >= "2026-09-01"]
    model = make_model(name, iterations=50).fit(train)
    out = model.predict(test)
    assert list(out.columns) == Q_COLS + ["pred"]
    assert out.index.equals(test.index)
    q = out[Q_COLS].to_numpy()
    assert (q >= 0).all()                                 # 음수 없음
    assert (np.diff(q, axis=1) >= 0).all()                # p10 ≤ p40 ≤ p50 ≤ p60 ≤ p80 ≤ p90


def test_feature_sets_differ(frame):
    m1 = make_model("M1", iterations=10).fit(frame)
    m2 = make_model("M2", iterations=10).fit(frame)
    assert "rain_mm" not in m1.features and "rain_mm" in m2.features
    assert set(m2.signal_cols) == {"temp_diff", "rain_mm"}


def test_sold_out_rows_are_not_used_for_training(frame):
    model = make_model("M1", iterations=10).fit(frame)
    n_sold_out = int(frame["sold_out"].astype(bool).sum())
    assert n_sold_out > 0
    assert model.n_dropped_sold_out == n_sold_out
    assert model.n_dropped_no_base == frame["menu"].nunique()     # 메뉴마다 첫날 1행 (과거 판매 없음)
    assert model.n_train == int(frame["qty"].notna().sum()) - n_sold_out - model.n_dropped_no_base


def test_short_data_mode_switches_automatically(frame):
    short = frame[frame["date"] < frame["date"].min() + pd.Timedelta(days=35)]
    model = make_model("M2", iterations=10).fit(short)
    assert model.short_mode is True
    assert model.predict(short).notna().all().all()
