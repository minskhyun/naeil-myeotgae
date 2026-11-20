"""기상청 단기예보로 오늘 이후 날씨를 external_daily.csv 에 채운다.

공공데이터포털 '기상청_단기예보 조회서비스' 활용신청이 필요하다.

backend 폴더에서 실행 (build_external_daily, academic 다음에):
    python -m collectors.forecast
"""
import argparse
import csv
import datetime as dt
import json
import math
import os
import re
from pathlib import Path

import requests
from dotenv import load_dotenv

from collectors.holidays import fetch_holidays
from collectors.store import DAILY_FILE, ENV_HINT, EVENTS_FILE, get_store, plan_schools

FCST_URL = "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
KST = dt.timezone(dt.timedelta(hours=9))
BASE_HOURS = [2, 5, 8, 11, 14, 17, 20, 23]   # 하루 8번 발표, 발표 후 약 10분 뒤 조회 가능


def to_grid(lat: float, lon: float):
    """위경도를 기상청 격자 좌표(nx, ny)로 바꾼다. 기상청 공식 변환식."""
    RE, GRID, SLAT1, SLAT2, OLON, OLAT, XO, YO = 6371.00877, 5.0, 30.0, 60.0, 126.0, 38.0, 43, 136
    D = math.pi / 180.0
    re_ = RE / GRID
    slat1, slat2, olon, olat = SLAT1 * D, SLAT2 * D, OLON * D, OLAT * D
    sn = math.log(math.cos(slat1) / math.cos(slat2)) / math.log(
        math.tan(math.pi * 0.25 + slat2 * 0.5) / math.tan(math.pi * 0.25 + slat1 * 0.5))
    sf = math.tan(math.pi * 0.25 + slat1 * 0.5) ** sn * math.cos(slat1) / sn
    ro = re_ * sf / math.tan(math.pi * 0.25 + olat * 0.5) ** sn
    ra = re_ * sf / math.tan(math.pi * 0.25 + lat * D * 0.5) ** sn
    theta = lon * D - olon
    theta = (theta + math.pi) % (2 * math.pi) - math.pi
    theta *= sn
    nx = math.floor(ra * math.sin(theta) + XO + 0.5)
    ny = math.floor(ro - ra * math.cos(theta) + YO + 0.5)
    return nx, ny


def latest_base(now: dt.datetime):
    """지금 조회할 수 있는 가장 최근 발표 시각."""
    for h in reversed(BASE_HOURS):
        base = now.replace(hour=h, minute=0, second=0, microsecond=0)
        if now >= base + dt.timedelta(minutes=10):
            return base
    yesterday = now - dt.timedelta(days=1)
    return yesterday.replace(hour=23, minute=0, second=0, microsecond=0)


def parse_pcp(text: str) -> float:
    """강수량 표기를 mm 숫자로. '강수없음'=0, '1mm 미만'=0.5, '30.0~50.0mm'=40, '50.0mm 이상'=50."""
    t = text.strip()
    if t in ("강수없음", "", "-"):
        return 0.0
    if "미만" in t:
        return 0.5
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", t)]
    if not nums:
        return 0.0
    if "~" in t and len(nums) >= 2:
        return (nums[0] + nums[1]) / 2
    return nums[0]


def fetch_forecast(service_key: str, nx: int, ny: int, base: dt.datetime):
    """발표 시각 base 의 예보 항목 전체를 돌려준다."""
    items, page = [], 1
    while True:
        params = {
            "serviceKey": service_key, "pageNo": page, "numOfRows": 1000, "dataType": "JSON",
            "base_date": base.strftime("%Y%m%d"), "base_time": base.strftime("%H%M"),
            "nx": nx, "ny": ny,
        }
        resp = requests.get(FCST_URL, params=params, timeout=30)
        resp.raise_for_status()
        try:
            body = resp.json()["response"]
        except (ValueError, KeyError):
            raise RuntimeError(f"단기예보 API 응답을 읽을 수 없음: {resp.text[:300]}")
        code = body["header"]["resultCode"]
        if code != "00":
            raise RuntimeError(f"단기예보 API 오류 {code}: {body['header'].get('resultMsg')}")
        items += body["body"]["items"]["item"]
        if page * 1000 >= int(body["body"]["totalCount"]):
            return items
        page += 1


def daily_summary(items: list):
    """시간별 예보를 날짜별로 묶는다. 24시간이 다 있는 날만 돌려준다."""
    by_day = {}
    for it in items:
        day = by_day.setdefault(it["fcstDate"], {"tmp": {}, "pcp": {}, "tmn": None, "tmx": None})
        cat, val, hour = it["category"], it["fcstValue"], it["fcstTime"]
        if cat == "TMP":
            day["tmp"][hour] = float(val)
        elif cat == "PCP":
            day["pcp"][hour] = parse_pcp(val)
        elif cat == "TMN":
            day["tmn"] = float(val)
        elif cat == "TMX":
            day["tmx"] = float(val)

    result = {}
    for ymd, d in by_day.items():
        if len(d["tmp"]) < 24:   # 발표 시각 이전 시간이 빠진 날은 평균이 치우치므로 쓰지 않는다
            continue
        temps = list(d["tmp"].values())
        key = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}"
        result[key] = {
            "temp_mean": round(sum(temps) / len(temps), 1),
            "temp_min": d["tmn"] if d["tmn"] is not None else min(temps),
            "temp_max": d["tmx"] if d["tmx"] is not None else max(temps),
            "rain_mm": round(sum(d["pcp"].values()), 1),
        }
    return result


def academic_counts(events_path: Path, schools):
    if not events_path.exists():
        return {}
    from collectors.academic import daily_counts
    return daily_counts(json.loads(events_path.read_text(encoding="utf-8")), schools)


RECENT_DAYS = 3   # 오늘 · 어제 · 그제 (기상청은 지난 발표분을 며칠만 보관한다)


def with_today(forecast: dict, issued: dict, fetch, now: dt.datetime):
    """오늘(과 관측 자료가 아직 없는 어제·그제) 날씨를 채운다 (11/20).

    최신 발표에는 오늘의 지난 시간이 없어 daily_summary가 오늘을 버리고, 관측 자료(ASOS)는 어제까지만,
    그것도 다음 날 오전에야 온다. 그래서 어제까지의 판매 기록을 오늘 올리면(예측 날짜 = 오늘) 그날 날씨가 비어 있었다.
    → D일의 날씨는 D-1일 17시 발표분에서 가져온다 (D일 24시간이 모두 들어 있다).
    발표 시각을 D-1일 17시로 적어 두어야 '예측 시점(전날 영업 종료)에 알던 정보'로 인정된다 (ml/features.issue_time).
    관측값이 있는 날은 update_csv가 덮어쓰지 않는다.  fetch(base) = 그 발표 시각의 예보 항목들.
    """
    for back in range(RECENT_DAYS):
        day = now.date() - dt.timedelta(days=back)
        eve = (now - dt.timedelta(days=back + 1)).replace(hour=17, minute=0, second=0, microsecond=0)
        try:
            early = daily_summary(fetch(eve))
        except Exception as err:   # 그날 날씨만 없이 계속 (내일 이후 예보는 그대로 쓴다)
            print(f"  [warn] {eve:%m-%d %H시} 발표 예보를 받지 못해 {day} 날씨는 비워 둠: {type(err).__name__}")
            continue
        if day.isoformat() in early:
            forecast[day.isoformat()], issued[day.isoformat()] = early[day.isoformat()], eve.isoformat()


def update_csv(path: Path, forecast: dict, issued: dict, holidays: dict, counts: dict):
    """issued = {날짜: 그 날짜의 예보가 발표된 시각}"""
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames)
        rows = {r["date"]: r for r in reader}
    if "weather_issued_at" not in fields:
        fields.append("weather_issued_at")

    # 마지막 날짜부터 예보 마지막 날까지 빈 날짜 줄을 만든다
    last = max(dt.date.fromisoformat(d) for d in rows)
    end = max([last] + [dt.date.fromisoformat(d) for d in forecast])
    day = last + dt.timedelta(days=1)
    while day <= end:
        key = day.isoformat()
        rows[key] = {c: "" for c in fields}
        rows[key].update({
            "date": key, "dow": day.weekday(), "is_weekend": int(day.weekday() >= 5),
            "is_holiday": int(key in holidays), "holiday_name": holidays.get(key, ""),
        })
        for col in ("exam_period", "vacation", "festival"):
            if col in fields:
                rows[key][col] = counts.get((key, col), 0)
        day += dt.timedelta(days=1)

    written = []
    for key, w in sorted(forecast.items()):
        row = rows[key]
        if row.get("weather_kind") == "observed":   # 관측값이 있으면 덮어쓰지 않는다
            continue
        row.update(w)
        row["weather_kind"] = "forecast"
        row["weather_issued_at"] = issued[key]
        written.append(key)

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for key in sorted(rows):
            writer.writerow({c: rows[key].get(c, "") for c in fields})
    return written


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", default=None)
    parser.add_argument("--lat", type=float, default=None)
    parser.add_argument("--lon", type=float, default=None)
    parser.add_argument("--daily", default=DAILY_FILE)
    parser.add_argument("--events", default=EVENTS_FILE)
    args = parser.parse_args()

    load_dotenv()
    key = os.environ.get("DATA_GO_KR_KEY")
    if not key:
        raise SystemExit(f"{ENV_HINT} 에 DATA_GO_KR_KEY 가 없습니다.")
    path = Path(args.daily)
    if not path.exists():
        raise SystemExit(f"{path} 가 없습니다. build_external_daily 를 먼저 실행하세요.")

    store = get_store(args.store)
    lat = args.lat if args.lat is not None else store["lat"]
    lon = args.lon if args.lon is not None else store["lon"]
    nx, ny = to_grid(lat, lon)
    now = dt.datetime.now(KST)
    base = latest_base(now)
    print(f"격자 {nx},{ny} / 발표 {base:%Y-%m-%d %H:%M}", flush=True)

    forecast = daily_summary(fetch_forecast(key, nx, ny, base))
    issued = {d: base.isoformat() for d in forecast}
    with_today(forecast, issued, lambda b: fetch_forecast(key, nx, ny, b), now)
    if not forecast:
        raise SystemExit("24시간이 모두 있는 예보 날짜가 없습니다.")
    days = sorted(forecast)
    try:
        holidays = fetch_holidays(dt.date.fromisoformat(days[0]) - dt.timedelta(days=7),
                                  dt.date.fromisoformat(days[-1]), key)
    except Exception as err:   # 특일 정보 API 활용신청 전 등: 공휴일 없이 예보만 넣는다
        print(f"  [warn] 공휴일 조회 실패, 공휴일 없이 계속: {type(err).__name__}")
        holidays = {}
    written = update_csv(path, forecast, issued, holidays, academic_counts(Path(args.events), plan_schools(store["store_id"])))
    for d in written:
        w = forecast[d]
        print(f"[ok] {d} 평균 {w['temp_mean']}도 (최저 {w['temp_min']}, 최고 {w['temp_max']}), 강수 {w['rain_mm']}mm")


if __name__ == "__main__":
    main()
