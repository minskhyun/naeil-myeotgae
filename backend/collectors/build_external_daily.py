"""external_daily.csv 만들기: 날짜 효과 + 공휴일 + 관측 날씨.

backend 폴더에서 실행:
    python -m collectors.build_external_daily --start 2025-11-01 --end 2026-11-16
"""
import argparse
import csv
import datetime as dt
import os
from pathlib import Path

from dotenv import load_dotenv

from collectors.holidays import fetch_holidays
from collectors.weather import fetch_observed

COLUMNS = [
    "date", "dow", "is_weekend", "is_holiday", "holiday_name",
    "temp_mean", "temp_min", "temp_max", "rain_mm", "weather_kind",
]


def build_rows(start: dt.date, end: dt.date, weather: dict, holidays: dict):
    rows = []
    day = start
    while day <= end:
        key = day.isoformat()
        w = weather.get(key, {})
        rows.append({
            "date": key,
            "dow": day.weekday(),               # 0=월 ... 6=일
            "is_weekend": int(day.weekday() >= 5),
            "is_holiday": int(key in holidays),
            "holiday_name": holidays.get(key, ""),
            "temp_mean": w.get("temp_mean", ""),
            "temp_min": w.get("temp_min", ""),
            "temp_max": w.get("temp_max", ""),
            "rain_mm": w.get("rain_mm", ""),
            "weather_kind": "observed" if w else "",  # 관측값이 아직 없는 날은 비워 둔다
        })
        day += dt.timedelta(days=1)
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--out", default="data/external_daily.csv")
    args = parser.parse_args()

    load_dotenv()
    key = os.environ.get("DATA_GO_KR_KEY")
    if not key:
        raise SystemExit("backend/.env 에 DATA_GO_KR_KEY 가 없습니다.")

    start = dt.date.fromisoformat(args.start)
    end = dt.date.fromisoformat(args.end)

    weather = fetch_observed(start, end, key)
    try:
        holidays = fetch_holidays(start, end, key)
    except Exception as err:   # 특일 정보 API 활용신청 전 등: 공휴일 없이 계속 (예측 엔진은 자체 공휴일 목록도 있음)
        print(f"  [warn] 공휴일 조회 실패, 공휴일 없이 계속: {str(err)[:120]}")
        holidays = {}
    rows = build_rows(start, end, weather, holidays)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"saved {out}: {len(rows)} days, weather {len(weather)} days, holidays {len(holidays)} days")


if __name__ == "__main__":
    main()