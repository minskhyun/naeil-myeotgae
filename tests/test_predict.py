"""predict.py 테스트: 준비량, 근거 문장, 내일 예측의 시점 규칙·형식."""
from pathlib import Path

import pandas as pd
import pytest

from contracts.schemas import Forecast
from ml.features import load_sales, load_signals
from ml.predict import prep_qty, predict_next_day, reason_text, write_forecast

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample" / "sinchon-a"
GROUPS = ["weather", "events"]


# ---------------------------------------------------------------- 준비량·문장 (손 계산)

def test_prep_qty_modes():
    q = pd.DataFrame({"p40": [38.1, 37.0], "pred": [40.2, 40.0000001], "p80": [47.1, 45.0]})
    assert prep_qty(q, "균형").tolist() == [41, 40]           # 올림 (계산 찌꺼기 40.0000001은 40)
    assert prep_qty(q, "폐기 줄이기").tolist() == [39, 37]     # 예상보다 조금 적게
    assert (prep_qty(q, "폐기 줄이기") <= prep_qty(q, "균형")).all()
    assert prep_qty(q, "품절 줄이기").tolist() == [48, 45]
    with pytest.raises(ValueError):
        prep_qty(q, "많이")
    rare = pd.DataFrame({"p40": [0.0], "pred": [0.3], "p80": [0.0]})    # 가끔 한 개 팔리는 메뉴: 중앙값은 0, 평균은 0.3
    assert [int(prep_qty(rare, m)[0]) for m in ("폐기 줄이기", "균형", "품절 줄이기")] == [0, 1, 1]   # 순서를 지킨다


def test_reason_text():
    assert reason_text("rain_mm", 12.0, -13.4) == "비 예보(12mm)로 평소보다 약 13% 적게 예상"
    assert reason_text("nearby_event", 1.0, 18.0) == "근처 행사가 있어 평소보다 약 18% 많이 예상"
    assert reason_text("temp_diff", -11.9, -14.2) == "기온이 최근 평균보다 12도 낮아 평소보다 약 14% 적게 예상"
    assert reason_text("trend_level", 1.5, 8.2) == "이 메뉴 검색량이 그 전 4주보다 50% 늘어 평소보다 약 8% 많이 예상"
    assert reason_text("trend_level", 0.7, -5.0) == "이 메뉴 검색량이 그 전 4주보다 30% 줄어 평소보다 약 5% 적게 예상"


# ---------------------------------------------------------------- 내일 예측

@pytest.fixture(scope="module")
def sample():
    return load_sales(SAMPLE / "sales.csv"), load_signals(SAMPLE / "signals.csv")


@pytest.fixture(scope="module")
def forecast(sample):
    sales, signals = sample
    return predict_next_day(sales, signals, GROUPS, "M3", iterations=30)


def test_forecast_next_day(forecast, tmp_path):
    assert {r.date for r in forecast.rows} == {pd.Timestamp("2026-11-01").date()}
    menus = [r.menu for r in forecast.rows]
    assert len(menus) == 10 and "두바이쫀득쿠키" not in menus        # 단종 메뉴는 예측 안 함
    assert forecast.signals_used == ["temp_diff", "rain_mm", "exam_period", "vacation", "festival", "nearby_event",
        "exam_period_diff", "vacation_diff", "festival_diff"]
    for r in forecast.rows:
        assert r.prep_qty >= r.pred and r.p10 <= r.pred <= r.p90     # 균형 = 예상 판매량(평균) 올림
        assert all(abs(x.effect_pct) >= 3 for x in r.reasons)
        assert not {x.signal for x in r.reasons} & {"vacation_diff", "exam_period_diff", "festival_diff"}  # 원재료 근거에 묶임
        assert [abs(x.effect_pct) for x in r.reasons] == sorted((abs(x.effect_pct) for x in r.reasons), reverse=True)
    path = write_forecast(forecast, tmp_path)
    assert Forecast.model_validate_json(path.read_text(encoding="utf-8")) == forecast


def test_rain_reason_uses_latest_forecast_and_its_source(forecast):
    rain = [x for r in forecast.rows for x in r.reasons if x.signal == "rain_mm"]
    assert rain and all(x.effect_pct < 0 for x in rain)               # 비 → 덜 팔림
    assert all("9.7mm" in x.text for x in rain)                       # 10/31 17:00 발표본 (10/30 발표본은 15.1mm)
    assert all(x.source_url == "https://www.weather.go.kr" for x in rain)


def test_forecast_published_after_close_is_ignored(sample, forecast):
    """10/31 22:00(영업 종료 21:00 이후)에 나온 예보는 11/1 예측에 쓰면 안 된다."""
    sales, signals = sample
    late = pd.DataFrame([dict(date=pd.Timestamp("2026-11-01"), store_id="sinchon-a", signal="rain_mm", value=80.0,
                              source_url="https://late.example", published_at=pd.Timestamp("2026-10-31 22:00"),
                              kind="forecast")])
    again = predict_next_day(sales, pd.concat([signals, late], ignore_index=True), GROUPS, "M3", iterations=30)
    assert [(r.menu, r.pred, r.p10, r.p90) for r in again.rows] == [(r.menu, r.pred, r.p10, r.p90) for r in forecast.rows]


def test_without_signals_has_no_reasons(sample):
    sales, signals = sample
    fc = predict_next_day(sales, signals, [], "M1", iterations=30)
    assert fc.signals_used == [] and all(r.reasons == [] for r in fc.rows)


def test_calibration_widens_range_but_keeps_pred(sample, forecast):
    sales, signals = sample
    shifts = {"p10": -0.2, "p40": -0.05, "p60": 0.0, "p80": 0.1, "p90": 0.3}
    fc = predict_next_day(sales, signals, GROUPS, "M3", calibration=shifts, iterations=30)
    for a, b in zip(forecast.rows, fc.rows):
        assert b.pred == a.pred and b.p10 <= a.p10 and b.p90 > a.p90


def test_short_data(sample):
    sales, signals = sample
    short = sales[sales["date"] < sales["date"].min() + pd.Timedelta(days=35)]
    fc = predict_next_day(short, signals, ["weather"], "M2", iterations=30)
    assert fc.rows and {r.date for r in fc.rows} == {(short["date"].max() + pd.Timedelta(days=1)).date()}


def test_menus_list_drops_discontinued(sample):
    """5일 전에 단종한 소금빵: 목록이 없으면 평소처럼 예측되고, store.json의 menus에서 빼면 예측하지 않는다."""
    sales, _ = sample
    sales = sales.assign(date=pd.to_datetime(sales["date"]))
    gone = sales[~((sales["menu"] == "소금빵") & (sales["date"] > sales["date"].max() - pd.Timedelta(days=5)))]
    auto = predict_next_day(gone, None, [], "M1", iterations=30)
    assert "소금빵" in {r.menu for r in auto.rows}                    # 자동 규칙(최근 14일)으로는 남아 있음
    menus = sorted(set(sales["menu"]) - {"소금빵"})
    fc = predict_next_day(gone, None, [], "M1", menus=menus, iterations=30)
    # 목록에 있어도 최근 14일 판매가 없는 메뉴(가상 데이터의 두바이쫀득쿠키)는 예측할 수 없다
    assert {r.menu for r in fc.rows} == {r.menu for r in auto.rows} - {"소금빵"}


def test_vacation_reason_includes_its_diff(sample):
    """방학 3일째(6/23): vacation과 vacation_diff는 근거 하나로 묶여 '방학이라 덜 팔림'으로 나온다."""
    sales, signals = sample
    sales = sales[sales["date"] < pd.Timestamp("2026-06-23")]
    fc = predict_next_day(sales, signals, GROUPS, "M3", iterations=30)
    vac = [x for r in fc.rows for x in r.reasons if x.signal == "vacation"]
    assert vac and all(x.effect_pct < 0 and x.text.startswith("방학 기간이라") for x in vac)
    assert not {x.signal for r in fc.rows for x in r.reasons} & {"vacation_diff", "exam_period_diff", "festival_diff"}


def test_reason_for_days_before_special_day():
    """기념일을 앞둔 날의 근거 문장: 신호 값 7 = 하루 전, 1 = 일주일 전."""
    from ml.predict import reason_text
    assert reason_text("special_lead", 7, 12.0) == "기념일을 1일 앞두고 있어 평소보다 약 12% 많이 예상"
    assert reason_text("special_lead", 1, -4.0) == "기념일을 7일 앞두고 있어 평소보다 약 4% 적게 예상"
