"""가상 매장 데이터 생성기 (신촌 A 베이커리카페, 2025-11-01 ~ 2026-10-31).

실제 데이터가 아니다. 예측 엔진 전체(ingest → features → models → evaluate → predict)를
실제 POS 없이 끝까지 개발·검증하려고 만든다. 효과를 일부러 심어 두고 정답은 truth.json에 남긴다.

만드는 파일 (data/sample/sinchon-a/)
- pos_raw.csv      포스에서 내보낸 것 같은 원본 (한글 열 이름, 메뉴명 변경, 0개 판매 행 없음) → ingest.py 개발용
- sales.csv        정리된 판매 기록 (SalesRow 형식, sold_out은 '진짜' 품절 여부)          → features.py 개발용
- signals.csv      외부 신호 (SignalRow 형식: 날씨 예보·관측, 학사일정, 근처 행사)
- store.json       매장 설정 (영업 종료 시각)
- truth.json       심어 둔 효과 (정답지)
- demand_true.csv  품절로 잘리기 전의 '진짜 수요' (품절 보정이 맞는지 확인용)

실행: 프로젝트 최상위 폴더에서  python -m ml.sample_data
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from contracts.schemas import SalesRow, SignalRow
from ml.calendar_kr import CLOSED, HOLIDAYS, period_of

STORE_ID = "sinchon-a"
CLOSE_TIME = "21:00"
OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "sample" / STORE_ID

# ---------------------------------------------------------------- 심어 둔 효과
# base: 학기 중 평일, 맑은 날, 15도일 때 하루 기대 판매량
MENUS = {
    "아이스 아메리카노": dict(base=62, price=3800, ice=True),
    "아메리카노(HOT)":   dict(base=34, price=3500, hot=True),
    "아이스 카페라떼":   dict(base=24, price=4500, ice=True),
    "카페라떼(HOT)":     dict(base=16, price=4300, hot=True),
    "소금빵":           dict(base=58, price=3200, cap=80),     # cap: 하루에 굽는 개수 → 넘으면 품절
    "크루아상":         dict(base=32, price=3800),
    "에그타르트":       dict(base=24, price=3000, cap=36),
    "베이글":           dict(base=20, price=3500),
    "휘낭시에":         dict(base=24, price=2500),
    "식빵":             dict(base=11, price=6500, resident=True),  # 동네 주민 메뉴 (학생 메뉴와 반대로 움직임)
}
TREND_MENU = "두바이쫀득쿠키"   # 기간 한정 유행 메뉴 (12/15 출시 → 4/15 단종)
WEEKDAY = np.array([1.00, 1.06, 1.06, 1.00, 0.94, 0.72, 0.62])            # 월~일
WEEKDAY_RESIDENT = np.array([0.95, 0.95, 0.95, 0.95, 1.00, 1.25, 1.15])
PERIOD = {"학기": 1.00, "시험기간": 1.15, "방학": 0.62, "축제": 1.45}
PERIOD_RESIDENT = {"학기": 1.00, "시험기간": 1.00, "방학": 0.92, "축제": 1.10}
HOLIDAY_F = 0.70
RAIN_F, HEAVY_RAIN_F = 0.86, 0.88       # 1mm 이상 비 / 20mm 이상이면 추가로 곱함
ICE_SLOPE, HOT_SLOPE = 0.040, -0.035     # 기온 1도당 (로그 기울기)
EVENT_F = 1.20                           # 근처 행사 날 (주민 메뉴 제외)
NOISE_CV = 0.11                          # 날마다 생기는 우연한 흔들림 (약 11%)

# 날씨 예보의 정확도: 이틀 전 예보 < 하루 전 예보
FORECASTS = [  # (며칠 전, 발표 시각, 기온 오차 표준편차, 비를 놓치거나 잘못 예보할 확률)
    (2, "17:00", 2.0, 0.25),
    (1, "17:00", 1.2, 0.12),
]
# 내일(판매 기록 다음 날, 11/1) 예보: 화면·근거 문장 개발용 '비 오는 날' 시나리오 (일부러 정한 값)
TOMORROW = dict(rain_mm=12.0, temp_change=-3.0)   # 비 12mm 안팎, 마지막 날보다 3도 낮음
KMA_URL = "https://www.weather.go.kr"
ACADEMIC_URL = "https://www.yonsei.ac.kr/sc/support/calendar.jsp"


def _weather(days: pd.DatetimeIndex, rng) -> pd.DataFrame:
    """서울 기후와 비슷한 가상 '관측' 날씨."""
    doy = days.day_of_year.values
    season = 12.5 + 14.5 * np.sin(2 * np.pi * (doy - 110) / 365)   # 1월 중순 최저, 8월 초 최고
    noise = np.zeros(len(days))
    for i in range(1, len(days)):
        noise[i] = 0.7 * noise[i - 1] + rng.normal(0, 2.0)          # 어제와 비슷한 날씨가 이어짐
    month = days.month.values
    rain_p = np.select([np.isin(month, [7, 8]), np.isin(month, [6, 9]), np.isin(month, [12, 1, 2])],
                       [0.48, 0.30, 0.16], default=0.24)
    is_rain = rng.random(len(days)) < rain_p
    rain = np.where(is_rain, np.round(rng.gamma(0.8, 14, len(days)) + 0.5, 1), 0.0)
    return pd.DataFrame({"date": days, "temp_mean": np.round(season + noise, 1), "rain_mm": rain})


def _forecast(wx: pd.DataFrame, sd_temp: float, miss: float, rng) -> pd.DataFrame:
    """관측값에 오차를 섞어 '그때 발표됐을 예보'를 만든다."""
    n = len(wx)
    temp = np.round(wx["temp_mean"].values + rng.normal(0, sd_temp, n), 1)
    obs = wx["rain_mm"].values
    rain = obs * np.exp(rng.normal(0, 0.4, n))                          # 양은 ±40% 안팎으로 틀림
    rain = np.where((obs > 0) & (rng.random(n) < miss), 0.0, rain)      # 온 비를 놓침
    false_alarm = (obs == 0) & (rng.random(n) < miss / 2)
    rain = np.where(false_alarm, rng.gamma(1.0, 5.0, n), rain)          # 안 온 비를 예보
    return pd.DataFrame({"date": wx["date"], "temp_mean": temp, "rain_mm": np.round(rain, 1)})


def _events(days: pd.DatetimeIndex, rng) -> pd.DataFrame:
    """근처 행사(공연 등) 25일. 대부분 며칠~몇 주 전에 공지되지만 20%는 당일 아침에야 공지된다."""
    candidates = [d for d in days if period_of(d) in ("학기", "시험기간") and d not in CLOSED]
    picked = pd.DatetimeIndex(sorted(rng.choice(candidates, size=25, replace=False)))
    late = rng.random(len(picked)) < 0.2
    lead = rng.integers(2, 22, len(picked))
    published = [d + pd.Timedelta(hours=9) if is_late else d - pd.Timedelta(days=int(k)) + pd.Timedelta(hours=10)
                 for d, is_late, k in zip(picked, late, lead)]
    return pd.DataFrame({"date": picked, "published_at": published, "late": late})


def generate(out_dir: Path = OUT_DIR, seed: int = 20261113) -> None:
    rng = np.random.default_rng(seed)
    days = pd.date_range("2025-11-01", "2026-10-31", freq="D")
    out_dir.mkdir(parents=True, exist_ok=True)

    wx = _weather(days, rng)
    events = _events(days, rng)
    event_days = set(events["date"])

    # ---------- 판매: 기대값(심어 둔 효과의 곱) → 우연한 흔들림 → 품절로 잘림
    sales, demand_rows = [], []
    for i, d in enumerate(days):
        if d in CLOSED:
            continue
        per, wd = period_of(d), d.weekday()
        t, r = wx.at[i, "temp_mean"], wx.at[i, "rain_mm"]
        for name, m in MENUS.items():
            resident = m.get("resident", False)
            mu = m["base"] * (WEEKDAY_RESIDENT[wd] * PERIOD_RESIDENT[per] if resident
                              else WEEKDAY[wd] * PERIOD[per])
            if d in HOLIDAYS:
                mu *= HOLIDAY_F
            if r >= 1:
                mu *= RAIN_F * (HEAVY_RAIN_F if r >= 20 else 1.0)
            if m.get("ice"):
                mu *= np.exp(ICE_SLOPE * (t - 15))
            if m.get("hot"):
                mu *= np.exp(HOT_SLOPE * (t - 15))
            if d in event_days and not resident:
                mu *= EVENT_F
            demand = int(rng.poisson(mu * rng.gamma(1 / NOISE_CV**2, NOISE_CV**2)))
            cap = m.get("cap")
            qty = min(demand, cap) if cap else demand
            sales.append((d, name, qty, bool(cap and qty == cap)))      # 만든 만큼 다 팔림 = 품절
            demand_rows.append((d, name, demand))

    for d in pd.date_range("2025-12-15", "2026-04-15"):                 # 유행 메뉴: 빠르게 떴다가 서서히 식음
        if d in CLOSED:
            continue
        x = (d - pd.Timestamp("2025-12-15")).days
        mu = 60 * (np.exp(-((x - 32) / 18) ** 2) if x < 32 else np.exp(-(x - 32) / 22)) * WEEKDAY[d.weekday()]
        q = int(rng.poisson(max(mu, 0.5)))
        sales.append((d, TREND_MENU, q, False))
        demand_rows.append((d, TREND_MENU, q))

    sales = pd.DataFrame(sales, columns=["date", "menu", "qty", "sold_out"])
    sales.insert(1, "store_id", STORE_ID)
    sales = sales.sort_values(["date", "menu"]).reset_index(drop=True)

    # ---------- 외부 신호 (세로형: 한 행 = 날짜 하나의 신호 하나의 '발표본' 하나)
    sig = []
    def add(date, signal, value, url, published_at, kind):
        sig.append((date, STORE_ID, signal, float(value), url, published_at, kind))

    for k, at, sd, miss in FORECASTS:                                   # 예보: 그날 전에 발표
        fc = _forecast(wx, sd, miss, rng)
        for row in fc.itertuples():
            pub = row.date - pd.Timedelta(days=k) + pd.Timedelta(at + ":00")
            add(row.date, "temp_mean", row.temp_mean, KMA_URL, pub, "forecast")
            add(row.date, "rain_mm", row.rain_mm, KMA_URL, pub, "forecast")
    for row in wx.itertuples():                                         # 관측: 그날이 끝난 뒤 공개
        pub = row.date + pd.Timedelta(days=1, hours=1)
        add(row.date, "temp_mean", row.temp_mean, KMA_URL, pub, "observed")
        add(row.date, "rain_mm", row.rain_mm, KMA_URL, pub, "observed")
    for d in days:                                                      # 학사일정: 학기 시작 전에 공지
        pub = pd.Timestamp("2025-08-01 09:00") if d < pd.Timestamp("2026-03-01") else pd.Timestamp("2026-01-15 09:00")
        name = {"시험기간": "exam_period", "방학": "vacation", "축제": "festival"}.get(period_of(d))
        if name:                                                        # calendar는 '해당하는 날'만 기록 (없으면 0)
            add(d, name, 1, ACADEMIC_URL, pub, "calendar")
    for row in events.itertuples():
        add(row.date, "nearby_event", 1, "https://example.com/sinchon-events", row.published_at, "event")

    # 내일 예보 (판매 기록 다음 날). 관측값은 아직 없으므로 예보만 넣는다.
    # 난수를 따로 써서(seed+1) 위의 판매·신호 데이터는 이 부분이 없을 때와 똑같이 유지된다.
    tomorrow = days[-1] + pd.Timedelta(days=1)
    wx_t = pd.DataFrame({"date": [tomorrow], "rain_mm": [TOMORROW["rain_mm"]],
                         "temp_mean": [round(wx["temp_mean"].iloc[-1] + TOMORROW["temp_change"], 1)]})
    rng_t = np.random.default_rng(seed + 1)
    for k, at, sd, _ in FORECASTS:
        row = next(_forecast(wx_t, sd, 0.0, rng_t).itertuples())        # 비를 놓치지 않게(miss=0)
        pub = row.date - pd.Timedelta(days=k) + pd.Timedelta(at + ":00")
        add(row.date, "temp_mean", row.temp_mean, KMA_URL, pub, "forecast")
        add(row.date, "rain_mm", row.rain_mm, KMA_URL, pub, "forecast")

    signals = pd.DataFrame(sig, columns=["date", "store_id", "signal", "value", "source_url", "published_at", "kind"])
    signals = signals.sort_values(["date", "signal", "published_at"]).reset_index(drop=True)

    # ---------- 계약 형식 검사: 한 줄이라도 틀리면 여기서 멈춘다
    for rec in sales.to_dict("records"):
        SalesRow.model_validate(rec)
    for rec in signals.to_dict("records"):
        SignalRow.model_validate(rec)

    # ---------- 포스 원본처럼 만들기: 0개 판매는 행이 없고, 3월 전엔 메뉴명이 달랐다
    price = {k: v["price"] for k, v in MENUS.items()} | {TREND_MENU: 5500}
    raw = sales[sales["qty"] > 0].copy()
    raw.loc[(raw["date"] < "2026-03-02") & (raw["menu"] == "아이스 아메리카노"), "menu"] = "아메리카노(ICE)"
    raw = pd.DataFrame({"날짜": raw["date"].dt.strftime("%Y-%m-%d"), "메뉴명": raw["menu"],
                        "판매수량": raw["qty"], "판매금액": raw["qty"] * sales.loc[raw.index, "menu"].map(price)})

    # ---------- 저장 (엑셀에서 한글이 안 깨지게 utf-8-sig)
    fmt_date = lambda s: s.dt.strftime("%Y-%m-%d")
    raw.to_csv(out_dir / "pos_raw.csv", index=False, encoding="utf-8-sig")
    sales.assign(date=fmt_date(sales["date"])).to_csv(out_dir / "sales.csv", index=False, encoding="utf-8-sig")
    signals.assign(date=fmt_date(signals["date"]),
                   published_at=signals["published_at"].dt.strftime("%Y-%m-%dT%H:%M:%S")
                   ).to_csv(out_dir / "signals.csv", index=False, encoding="utf-8-sig")
    demand = pd.DataFrame(demand_rows, columns=["date", "menu", "demand"])
    demand.assign(date=fmt_date(demand["date"])).to_csv(out_dir / "demand_true.csv", index=False, encoding="utf-8-sig")

    with open(out_dir / "store.json", "w", encoding="utf-8") as f:
        json.dump({"store_id": STORE_ID, "name": "신촌 A 베이커리카페 (가상)", "close_time": CLOSE_TIME},
                  f, ensure_ascii=False, indent=1)
    truth = dict(
        weekday_main=WEEKDAY.tolist(), weekday_resident=WEEKDAY_RESIDENT.tolist(),
        period_main=PERIOD, period_resident=PERIOD_RESIDENT, holiday=HOLIDAY_F,
        rain=RAIN_F, heavy_rain_extra=HEAVY_RAIN_F, ice_slope=ICE_SLOPE, hot_slope=HOT_SLOPE,
        nearby_event=EVENT_F, noise_cv=NOISE_CV,
        caps={k: v["cap"] for k, v in MENUS.items() if "cap" in v},
        closed=[str(x.date()) for x in CLOSED], rename={"아메리카노(ICE)": "아이스 아메리카노"},
        forecasts=[dict(days_before=k, at=at, temp_sd=sd, rain_miss=miss) for k, at, sd, miss in FORECASTS],
        events_late=[str(d.date()) for d in events.loc[events["late"], "date"]],
        tomorrow=dict(date=str(tomorrow.date()), **wx_t.iloc[0].drop("date").to_dict()),
    )
    with open(out_dir / "truth.json", "w", encoding="utf-8") as f:
        json.dump(truth, f, ensure_ascii=False, indent=1)

    print(f"저장: {out_dir}")
    print(f"  sales.csv    {len(sales):>5}행  (품절 {int(sales['sold_out'].sum())}행)")
    print(f"  pos_raw.csv  {len(raw):>5}행  (0개 판매 행 제외)")
    print(f"  signals.csv  {len(signals):>5}행  " + str(signals.groupby('kind').size().to_dict()))


if __name__ == "__main__":
    generate()
