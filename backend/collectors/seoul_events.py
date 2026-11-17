"""서울시 문화행사 정보에서 매장 근처 행사를 골라 events.json, external_daily.csv 에 넣는다.

서울 열린데이터광장 '서울시 문화행사 정보' 인증키가 필요하다.

backend 폴더에서 실행:
    python -m collectors.seoul_events
    python -m collectors.seoul_events --refresh     # 행사 목록 새로 받기

원본 목록은 data/raw/seoul_culture/culturalEventInfo.json 에 저장하고 다시 쓴다.
"""
import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import re
from pathlib import Path

import requests
from dotenv import load_dotenv

from collectors.store import DAILY_FILE, ENV_HINT, EVENTS_FILE, distance_m, get_store, plan_event_radius

API = "http://openapi.seoul.go.kr:8088/{key}/json/culturalEventInfo/{start}/{end}/"
RAW_FILE = Path("data/raw/seoul_culture/culturalEventInfo.json")
KST = dt.timezone(dt.timedelta(hours=9))
PAGE = 1000
MAX_DAYS = 14   # 이보다 긴 상설 전시는 매일 1이 되어 신호가 안 되므로 뺀다


def fetch_all(key: str):
    rows, start = [], 1
    while True:
        url = API.format(key=key, start=start, end=start + PAGE - 1)
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        body = data.get("culturalEventInfo")
        if body is None:
            result = data.get("RESULT", {})
            if result.get("CODE") == "INFO-200":   # 더 이상 데이터 없음
                break
            raise RuntimeError(f"서울시 API 오류: {result}")
        code = body.get("RESULT", {}).get("CODE")
        if code not in ("INFO-000", None):
            raise RuntimeError(f"서울시 API 오류: {body.get('RESULT')}")
        rows += body.get("row", [])
        total = int(body["list_total_count"])
        print(f"  {len(rows)}/{total}건 받음", flush=True)
        if start + PAGE - 1 >= total:
            break
        start += PAGE
    return rows


def load_rows(key: str, refresh: bool):
    if RAW_FILE.exists() and not refresh:
        saved = json.loads(RAW_FILE.read_text(encoding="utf-8"))
        return saved["rows"], saved["fetched_at"]
    rows = fetch_all(key)
    fetched_at = dt.datetime.now(KST).isoformat(timespec="seconds")
    RAW_FILE.parent.mkdir(parents=True, exist_ok=True)
    RAW_FILE.write_text(json.dumps({"fetched_at": fetched_at, "rows": rows}, ensure_ascii=False),
                        encoding="utf-8")
    return rows, fetched_at


def _date(text):
    m = re.search(r"\d{4}-\d{2}-\d{2}", str(text or ""))
    return dt.date.fromisoformat(m.group()) if m else None


def _latlon(row):
    """LAT, LOT 중 한국 위도 범위(33~39)인 쪽을 위도로 본다. 필드 이름이 뒤바뀐 경우에 대비."""
    try:
        a, b = float(row.get("LAT") or 0), float(row.get("LOT") or 0)
    except ValueError:
        return None
    if 33 <= a <= 39 and 124 <= b <= 132:
        return a, b
    if 33 <= b <= 39 and 124 <= a <= 132:
        return b, a
    return None


def _event_id(row):
    m = re.search(r"cultcode=(\d+)", str(row.get("HMPG_ADDR", "")))
    if m:
        return f"seoul-{m.group(1)}"
    raw = f"{row.get('TITLE')}|{row.get('STRTDATE')}|{row.get('PLACE')}"
    return "seoul-" + hashlib.md5(raw.encode("utf-8")).hexdigest()[:10]


def select_events(rows, store, radius_m, fetched_at):
    events, skipped_long = [], 0
    for row in rows:
        pos = _latlon(row)
        start, end, rgst = _date(row.get("STRTDATE")), _date(row.get("END_DATE")), _date(row.get("RGSTDATE"))
        if not pos or not start or not end or end < start:
            continue
        dist = distance_m(store["lat"], store["lon"], *pos)
        if dist > radius_m:
            continue
        if (end - start).days + 1 > MAX_DAYS:
            skipped_long += 1
            continue
        events.append({
            "event_id": _event_id(row),
            "source": "seoul_culture",
            "store_id": store["store_id"],
            "type": "event",
            "category": row.get("CODENAME", ""),
            "title": row.get("TITLE", "").strip(),
            "place": row.get("PLACE", "").strip(),
            "distance_m": round(dist),
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "source_url": row.get("HMPG_ADDR") or row.get("ORG_LINK") or "",
            "published_at": f"{rgst.isoformat()}T00:00:00+09:00" if rgst else None,
            "fetched_at": fetched_at,
            "verified": True,
        })
    unique = {e["event_id"]: e for e in events}
    return sorted(unique.values(), key=lambda e: (e["start_date"], e["distance_m"])), skipped_long


def daily_counts(events):
    """날짜별 진행 중인 근처 행사 수. 그날보다 먼저 등록된 행사만 센다 (미래 정보 혼입 방지)."""
    counts = {}
    for e in events:
        pub = _date(e.get("published_at"))
        d, end = dt.date.fromisoformat(e["start_date"]), dt.date.fromisoformat(e["end_date"])
        while d <= end:
            if pub is None or pub < d:
                counts[d.isoformat()] = counts.get(d.isoformat(), 0) + 1
            d += dt.timedelta(days=1)
    return counts


def update_events_json(path: Path, events):
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    kept = [e for e in old if e.get("source") != "seoul_culture"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(kept + events, ensure_ascii=False, indent=2), encoding="utf-8")


def update_daily_csv(path: Path, counts):
    if not path.exists():
        print(f"  [warn] {path} 가 없어 CSV 는 건너뜀.")
        return
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames)
        rows = list(reader)
    if "nearby_event" not in fields:
        fields.append("nearby_event")
    for row in rows:
        row["nearby_event"] = counts.get(row["date"], 0)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", default=None)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--events", default=EVENTS_FILE)
    parser.add_argument("--daily", default=DAILY_FILE)
    args = parser.parse_args()

    load_dotenv()
    key = os.environ.get("SEOUL_DATA_KEY")
    if not key:
        raise SystemExit(f"{ENV_HINT} 에 SEOUL_DATA_KEY 가 없습니다.")

    store = get_store(args.store)
    radius = plan_event_radius(store["store_id"])
    rows, fetched_at = load_rows(key, args.refresh)
    events, skipped = select_events(rows, store, radius, fetched_at)
    update_events_json(Path(args.events), events)
    update_daily_csv(Path(args.daily), daily_counts(events))

    print(f"saved {args.events}: 반경 {radius}m 안 행사 {len(events)}건 "
          f"(전체 {len(rows)}건 중, {MAX_DAYS}일 넘는 장기 행사 {skipped}건 제외)")
    for e in events[-5:]:
        print(f"  {e['start_date']}~{e['end_date']} {e['distance_m']}m {e['title'][:30]}")


if __name__ == "__main__":
    main()
