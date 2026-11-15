"""features.py 테스트. 핵심은 누수 테스트 두 개 (TASKS.md §4)."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ml.features import SIGNAL_GROUPS, build_frame, feature_columns, issue_time, load_sales, load_signals

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample" / "sinchon-a"
ALL_SIGNALS = [n for names in SIGNAL_GROUPS.values() for n in names]


@pytest.fixture(scope="module")
def sales():
    return load_sales(SAMPLE / "sales.csv")


@pytest.fixture(scope="module")
def signals():
    return load_signals(SAMPLE / "signals.csv")


def _tiny_sales():
    """손으로 계산 가능한 작은 데이터: 메뉴 하나, 10일, qty = 1..10, 5일째(01-05)는 휴무."""
    days = pd.date_range("2026-01-01", periods=10)
    df = pd.DataFrame({"date": days, "store_id": "s", "menu": "빵", "qty": np.arange(1, 11), "sold_out": False})
    return df[df["date"] != "2026-01-05"]


# ---------------------------------------------------------------- 시점

def test_issue_time():
    assert issue_time("2026-03-19") == pd.Timestamp("2026-03-18 21:00")
    assert issue_time("2026-03-19", "19:00") == pd.Timestamp("2026-03-18 19:00")
    assert issue_time("2026-03-19", "02:00") == pd.Timestamp("2026-03-18 23:59")   # 자정 넘어 영업


# ---------------------------------------------------------------- 판매 이력 (손 계산과 비교)

def test_history_values_by_hand():
    f = build_frame(_tiny_sales()).set_index("date")
    assert pd.Timestamp("2026-01-05") not in f.index                # 휴무일은 행이 없다
    d6 = f.loc["2026-01-06"]                                        # 6일째: 전날(5일)이 휴무
    assert np.isnan(d6["lag_1"])
    assert d6["mean_7"] == pytest.approx((1 + 2 + 3 + 4) / 4)       # 지난 7일 중 판매 기록이 있는 날의 평균
    d8 = f.loc["2026-01-08"]
    assert d8["lag_1"] == 7 and d8["lag_7"] == 1 and np.isnan(d8["lag_14"])
    assert d8["days_since_start"] == 7
    assert np.isnan(f.loc["2026-01-03", "mean_28"])                 # 기록 7일 미만 → NaN


# ---------------------------------------------------------------- 누수 테스트 1: 미래 판매를 바꿔도 변수는 그대로

def test_leak_future_sales_do_not_change_features(sales):
    d = pd.Timestamp("2026-03-19")
    base = build_frame(sales)
    changed = sales.copy()
    changed.loc[changed["date"] >= d, "qty"] *= 100                 # D일 '이후'(당일 포함) 판매를 마구 바꿈
    changed.loc[changed["date"] >= d, "sold_out"] = True
    after = build_frame(changed)

    cols = [c for c in base.columns if c not in ("qty", "sold_out")]
    a = base[base["date"] == d][cols].reset_index(drop=True)
    b = after[after["date"] == d][cols].reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b)                             # D일 행의 변수는 하나도 안 바뀌어야 함


# ---------------------------------------------------------------- 누수 테스트 2: 신호의 공개 시각

def _versioned_signals():
    """3/19 rain_mm 발표본 4개 + 3/19 시험기간(calendar). published_at만 다르다."""
    rows = [
        ("2026-03-18 18:00", 1.0, "forecast"),
        ("2026-03-18 20:00", 2.0, "forecast"),
        ("2026-03-18 22:00", 3.0, "forecast"),
        ("2026-03-20 01:00", 4.0, "observed"),
    ]
    df = pd.DataFrame([{"date": pd.Timestamp("2026-03-19"), "store_id": "s", "signal": "rain_mm", "value": v,
                        "source_url": "-", "published_at": pd.Timestamp(p), "kind": k} for p, v, k in rows])
    cal = {"date": pd.Timestamp("2026-03-19"), "store_id": "s", "signal": "exam_period", "value": 1.0,
           "source_url": "-", "published_at": pd.Timestamp("2026-01-15 09:00"), "kind": "calendar"}
    return pd.concat([df, pd.DataFrame([cal])], ignore_index=True)


@pytest.mark.parametrize("close_time, expected", [("19:00", 1.0), ("21:00", 2.0), ("23:00", 3.0)])
def test_leak_signal_published_after_issue_time_is_not_used(close_time, expected):
    tiny = pd.DataFrame({"date": pd.date_range("2026-03-10", "2026-03-20"), "store_id": "s", "menu": "빵",
                         "qty": 5, "sold_out": False})
    f = build_frame(tiny, _versioned_signals(), ["rain_mm", "exam_period"], close_time=close_time).set_index("date")
    assert f.loc["2026-03-19", "rain_mm"] == expected     # 예측 시각 전에 나온 것 중 가장 늦은 발표본
    assert np.isnan(f.loc["2026-03-18", "rain_mm"])       # 신호가 없는 날의 예보 = 모름(NaN)
    assert f.loc["2026-03-19", "exam_period"] == 1
    assert f.loc["2026-03-18", "exam_period"] == 0        # 학사일정에 없는 날 = 해당 없음(0)


def test_late_announced_events_are_not_attached(sales, signals):
    f = build_frame(sales, signals, ["nearby_event"])
    ev = signals[signals["signal"] == "nearby_event"]
    late = ev[ev["published_at"] > ev["date"] - pd.Timedelta(days=1) + pd.Timedelta(hours=21)]
    on_time = ev.drop(late.index)
    assert len(late) > 0
    assert (f[f["date"].isin(late["date"])]["nearby_event"] == 0).all()
    assert (f[f["date"].isin(on_time["date"])]["nearby_event"] == 1).all()


# ---------------------------------------------------------------- 신호 이름·예측 행·짧은 데이터

def test_unknown_signal_name_only_warns(sales, signals):
    with pytest.warns(UserWarning, match="trend_level"):
        f = build_frame(sales, signals, ALL_SIGNALS)
    assert "trend_level" not in f.columns
    assert feature_columns("M3", f)[-9:] == ["temp_diff", "rain_mm", "exam_period", "vacation", "festival", "nearby_event",
        "exam_period_diff", "vacation_diff", "festival_diff"]


def test_temp_diff_by_hand():
    """temp_diff(D) = D의 기온 − (D 이전 날들의 기온 평균, 최대 28일, 최소 7일)."""
    days = pd.date_range("2026-01-01", periods=9)
    sales = pd.DataFrame({"date": days, "store_id": "s", "menu": "빵", "qty": 1, "sold_out": False})
    temps = [10, 10, 10, 10, 10, 10, 10, 3, 17]                     # 7일간 10도 → 8일째 3도, 9일째 17도
    signals = pd.DataFrame({"date": days, "store_id": "s", "signal": "temp_mean", "value": temps,
                            "source_url": "-", "published_at": days - pd.Timedelta(days=2), "kind": "forecast"})
    f = build_frame(sales, signals, ["temp_diff"]).set_index("date")["temp_diff"]
    assert f[:7].isna().all()                                      # 앞선 날이 7일 미만이면 평균을 안 냄
    assert f.iloc[7] == pytest.approx(3 - 10)                      # 오늘(3도)은 평균에 넣지 않음
    assert f.iloc[8] == pytest.approx(17 - (10 * 7 + 3) / 8)


def test_predict_rows_only_for_recently_sold_menus(sales):
    nxt = sales["date"].max() + pd.Timedelta(days=1)
    f = build_frame(sales, predict_dates=[nxt])
    pred = f[f["date"] == nxt]
    assert pred["qty"].isna().all()
    assert "두바이쫀득쿠키" not in set(pred["menu"])                  # 4월에 단종 → 예측 안 함
    assert len(pred) == 10
    assert pred["lag_1"].notna().all()                              # 예측 행도 어제 판매는 보인다


def test_short_data_35_days(sales, signals):
    short = sales[sales["date"] < sales["date"].min() + pd.Timedelta(days=35)]
    f = build_frame(short, signals, ["temp_mean", "rain_mm"])
    assert len(f) > 0
    assert f["mean_28"].isna().any() and f["mean_28"].notna().any()


def test_load_signals_json_matches_csv(tmp_path):
    """새얼이 JSON(SignalRow 목록)으로 줘도 CSV와 똑같이 읽히고, '+09:00'이 붙은 시각은 한국 시간으로 맞춘다."""
    import json
    rows = [dict(date="2026-11-01", store_id="s", signal="rain_mm", value=9.7, source_url="u",
                 published_at="2026-10-31T17:00:00+09:00", kind="forecast"),
            dict(date="2026-11-01", store_id="s", signal="nearby_event", value=1, source_url="u",
                 published_at="2026-10-20T01:00:00Z", kind="event")]          # UTC 01시 = KST 10시
    (tmp_path / "s.json").write_text(json.dumps(rows), encoding="utf-8")
    pd.DataFrame(rows).assign(published_at=["2026-10-31 17:00:00", "2026-10-20 10:00:00"]).to_csv(tmp_path / "s.csv", index=False)
    a, b = load_signals(tmp_path / "s.json"), load_signals(tmp_path / "s.csv")
    pd.testing.assert_frame_equal(a, b)
    assert a["published_at"].tolist() == [pd.Timestamp("2026-10-31 17:00"), pd.Timestamp("2026-10-20 10:00")]
