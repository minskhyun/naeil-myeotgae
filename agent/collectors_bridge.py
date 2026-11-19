"""공공 데이터 수집기(backend/collectors, 새얼 담당) 실행 + 결과를 예측 엔진 입력으로 바꾸기.

    수집기: python -m collectors.run_all (backend/ 에서 실행, 결과는 매장별 폴더 work_dir에)
      → {work_dir}/external_daily.csv           날짜당 한 줄 (날씨 관측·예보, 학사 기간 수, 근처 행사 수)
      → {work_dir}/events.json                  행사·학사일정 목록 (출처, 게시 시각, 매장과의 거리)
      → {work_dir}/{store_id}_nearby.json       카카오로 찾은 주변 시설
      → {work_dir}/{store_id}_sources.json      정보원 계획 (Claude가 고른 학교·행사 반경과 그 이유)
    work_dir = data/artifacts/{store_id}/collectors (run.py가 정함, 커밋 안 됨)
    이 파일이 하는 일: 위 결과 → SignalRow(시점 규칙용 공개 시각 포함) + CollectionItem(AI 주의 안내 원문)
    부르는 곳: agent/collect.py의 public_data

공개 시각을 붙이는 규칙
  - 날씨 관측값: '전날 17:10 예보'처럼 (실제 예보가 아님 → source_url 끝에 OBSERVED_PROXY, 결과를 말할 때 밝힐 것)
  - 날씨 예보: 수집기가 적은 발표 시각(weather_issued_at)
  - 학사 기간(exam_period·vacation·festival): 학사일정은 학기 전에 공개되므로 그 해 1월 1일 공개로 본다
    ※ 정보원 계획(어느 학교를 쓸지)이 없으면 수집기가 신촌 3개 대학을 모두 세므로, 계획이 없으면 쓰지 않는다
  - 근처 행사(nearby_event): events.json의 서울 문화행사를 다시 세어, 등록될 때마다 그날 행사 수를 한 줄씩
    (등록일 23:59 공개로 본다, 보수적). 예측 시각에는 그때까지 등록된 행사 수가 쓰인다
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd

from contracts.schemas import CollectionItem, SignalRow, StoreConfig
from ml import progress
from ml.features import to_kst
from ml.paths import ROOT

BACKEND = ROOT / "backend"
DAILY, EVENTS, STORES = "external_daily.csv", "events.json", "stores.json"      # work_dir 안의 파일 이름

OBSERVED_PROXY = "#관측값을-예보-대신-사용"     # 이 표시가 붙은 신호는 실제 예보가 아니다 (run.py가 줄 수를 알려 줌)
KMA_OBSERVED = "https://data.kma.go.kr"
KMA_FORECAST = "https://www.data.go.kr/data/15084084/openapi.do"
ACADEMIC_COLS = ["exam_period", "vacation", "festival"]
MAX_EVENT_DAYS = 14                            # 수집기(seoul_events)와 같은 기준 (이보다 긴 상설 전시는 신호가 안 됨)
# 수집기의 단계 이름 → 화면에 보여 줄 '지금 하는 일'
STAGE_TEXT = {"kakao": "매장 주변 시설을 살펴보는 중", "agent": "AI가 이 매장에 맞는 정보원을 고르는 중",
              "build_external_daily": "지난 날씨 기록을 받는 중", "forecast": "날씨 예보를 받는 중",
              "academic": "학교 일정을 읽는 중", "seoul_events": "서울시 문화행사를 찾는 중"}
MAX_PLACES_SHOWN = 70                          # 화면(지도)에 알릴 주변 시설 수 (가까운 순)
MAX_EVENTS_SHOWN = 15                          # 화면(지도)에 알릴 서울 문화행사 수 (예측 날짜에 가까운 순)


# ---------------------------------------------------------------- 수집기 실행

def ensure_store(store: StoreConfig, work_dir: Path) -> None:
    """수집기가 읽을 매장 목록({work_dir}/stores.json)을 이 매장 하나로 쓴다 (이름·주소·좌표).
    주소가 바뀌었으면 주변 시설·정보원 계획을 지워 다시 고르게 한다 (옛 동네의 학교·반경을 쓰지 않도록)."""
    work_dir.mkdir(parents=True, exist_ok=True)
    path = work_dir / STORES
    entry = dict(store_id=store.store_id, name=store.name or store.store_id, category=store.category,
                 address=store.address or "", lat=store.lat, lon=store.lon)
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        if old and old[0].get("address") != entry["address"]:
            for name in (f"{store.store_id}_nearby.json", f"{store.store_id}_sources.json"):
                (work_dir / name).unlink(missing_ok=True)
    path.write_text(json.dumps([entry], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_collectors(store_id: str, start: dt.date, end: dt.date, work_dir: Path) -> tuple[bool, list[str]]:
    """python -m collectors.run_all 을 backend/에서 실행 (결과는 work_dir에). 돌려주는 값: (성공 여부, 출력 마지막 몇 줄).
    수집기가 단계를 시작할 때마다('=== 이름 ===' 줄) 화면에 알린다: 지금 하는 일, 방금 끝난 단계가 찾은 것."""
    work_dir = Path(work_dir).resolve()        # 수집기는 backend/에서 돌므로 절대 경로로 넘긴다
    (work_dir / DAILY).unlink(missing_ok=True)  # 실패했을 때 지난번 결과를 이번 것으로 착각하지 않도록 먼저 지운다
    cmd = [sys.executable, "-m", "collectors.run_all", "--store", store_id,
           "--start", start.isoformat(), "--end", end.isoformat()]
    proc = subprocess.Popen(cmd, cwd=BACKEND, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                            errors="replace", env={**os.environ, "COLLECTORS_WORK_DIR": str(work_dir), "PYTHONIOENCODING": "utf-8"})
    lines, told = [], set()
    for line in proc.stdout:
        if line.strip():
            lines.append(hide_keys(line.rstrip()))
        stage = re.fullmatch(r"=== (\w+) ===", line.strip())
        if stage:
            tell_plan(store_id, work_dir, told)              # 앞 단계(주변 시설, 정보원 선택)가 끝났으면 그 결과를 알린다
            progress.status(STAGE_TEXT.get(stage.group(1), stage.group(1)))
    proc.wait()
    tell_plan(store_id, work_dir, told)
    return proc.returncode == 0 and (work_dir / DAILY).exists(), lines[-6:]


# ---------------------------------------------------------------- 화면에 알리기 (ml/progress.py)

def tell_plan(store_id: str, work_dir: Path, told: set | None = None) -> None:
    """주변 시설(가까운 순 일부)과 AI가 고른 정보원을 알린다. told: 이미 알린 것 (같은 것을 두 번 알리지 않게)."""
    told = told if told is not None else set()
    work_dir = Path(work_dir)
    nearby, plan = work_dir / f"{store_id}_nearby.json", work_dir / f"{store_id}_sources.json"
    places = json.loads(nearby.read_text(encoding="utf-8"))["places"] if nearby.exists() else []
    if places and "places" not in told:
        told.add("places")
        near = sorted((p for p in places if p.get("lat") and p.get("distance_m") is not None), key=lambda p: p["distance_m"])
        progress.emit("places", count=len(places), places=[
            dict(name=p["name"], group=p["group"], lat=p["lat"], lon=p["lon"], distance_m=p["distance_m"])
            for p in near[:MAX_PLACES_SHOWN]])
    if plan.exists() and "plan" not in told:
        told.add("plan")
        data, where = json.loads(plan.read_text(encoding="utf-8")), {p["name"]: p for p in places}
        picks = []                                           # 고른 정보원마다: 무엇을 · 근거가 된 시설(지도 위치) · 이유
        for a in data.get("academic") or []:
            at = where.get(a.get("evidence"), {})
            picks.append(dict(what="학교 일정", name=a.get("evidence"), lat=at.get("lat"), lon=at.get("lon"), reason=a.get("reason")))
        events = data.get("events") or {}
        for name in (events.get("evidence") or [])[:6]:
            at = where.get(name, {})
            picks.append(dict(what="근처 행사", name=name, lat=at.get("lat"), lon=at.get("lon"), reason=events.get("reason")))
        progress.emit("plan", method=data.get("method"), model=data.get("model"), radius_m=events.get("radius_m"),
                      reason=events.get("reason"), picks=[p for p in picks if p["lat"]])


def tell_results(store_id: str, work_dir: Path, rows: list[SignalRow], around: dt.date) -> None:
    """수집이 끝난 뒤: 날씨·학교 일정이 며칠치인지, 근처 서울 문화행사(around에 가까운 것부터 일부)."""
    days = lambda names: len({r.date for r in rows if r.signal in names})     # noqa: E731
    progress.emit("weather", days=days({"temp_mean", "rain_mm"}))
    if days(set(ACADEMIC_COLS)):
        progress.emit("academic", days=days(set(ACADEMIC_COLS)))
    path = Path(work_dir) / EVENTS
    events = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    mine = [e for e in events if e.get("source") == "seoul_culture" and e.get("store_id") == store_id and e.get("lat")]
    mine.sort(key=lambda e: abs((dt.date.fromisoformat(e["start_date"]) - around).days))
    for e in mine[:MAX_EVENTS_SHOWN]:
        progress.emit("event", title=e["title"], place=e.get("place"), lat=e["lat"], lon=e["lon"], start=e["start_date"],
                      end=e["end_date"], source="서울시 문화행사", url=e.get("source_url"))


def hide_keys(text: str) -> str:
    """오류 문장 속 요청 주소의 API 키를 가린다 (실행 기록이 웹 화면에 그대로 보이므로)."""
    return re.sub(r"(?i)((?:service)?key|apikey|api_key)=[^&\s'\"]+", r"\1=***", text)


# ---------------------------------------------------------------- 결과 → 신호

def weather_rows(store_id: str, daily: pd.DataFrame) -> list[SignalRow]:
    rows = []
    for r in daily.itertuples():
        if pd.isna(r.temp_mean) or not isinstance(r.weather_kind, str):
            continue
        day = pd.Timestamp(r.date)
        if r.weather_kind == "forecast" and isinstance(r.weather_issued_at, str):
            published, url = to_kst(r.weather_issued_at).to_pydatetime(), KMA_FORECAST
        else:                                               # 관측값 → 전날 17:10 예보처럼
            published, url = (day - pd.Timedelta(days=1) + pd.Timedelta(hours=17, minutes=10)).to_pydatetime(), \
                KMA_OBSERVED + OBSERVED_PROXY
        for signal in ("temp_mean", "rain_mm"):
            value = getattr(r, signal)
            if pd.notna(value):
                rows.append(SignalRow(date=day.date(), store_id=store_id, signal=signal, value=float(value),
                                      source_url=url, published_at=published, kind="forecast"))
    return rows


def academic_rows(store_id: str, daily: pd.DataFrame, events: list[dict]) -> list[SignalRow]:
    """학사 기간 수 (0인 날은 줄을 만들지 않음 → 예측 엔진이 0으로 채움)."""
    url = next((e["source_url"] for e in events if e.get("source") == "academic"), "")
    rows = []
    for r in daily.itertuples():
        day = pd.Timestamp(r.date).date()
        for col in ACADEMIC_COLS:
            value = getattr(r, col, 0)
            if pd.notna(value) and float(value) > 0:
                rows.append(SignalRow(date=day, store_id=store_id, signal=col, value=float(value), source_url=url,
                                      published_at=dt.datetime(day.year, 1, 1), kind="calendar"))
    return rows


def event_rows(store_id: str, events: list[dict], lo: dt.date, hi: dt.date
               ) -> tuple[list[SignalRow], list[CollectionItem]]:
    """서울 문화행사 → 날짜마다 '그때까지 등록된 행사 수' 줄들 + 행사마다 원문."""
    by_day: dict[dt.date, list[tuple[dt.datetime, dict]]] = {}
    items = []
    for e in events:
        if e.get("source") != "seoul_culture" or e.get("store_id") != store_id or not e.get("verified", True):
            continue
        s, t = dt.date.fromisoformat(e["start_date"]), dt.date.fromisoformat(e["end_date"])
        if (t - s).days + 1 > MAX_EVENT_DAYS:
            continue
        reg = e.get("published_at")
        published = (to_kst(reg).normalize() + pd.Timedelta(hours=23, minutes=59)).to_pydatetime() \
            if reg else dt.datetime.now().replace(microsecond=0)
        text = (f"{e['title']}. 장소: {e.get('place', '')} (매장에서 약 {e.get('distance_m', '?')}m). "
                f"기간: {e['start_date']} ~ {e['end_date']}. 분야: {e.get('category', '')}.")
        for d in pd.date_range(max(s, lo), min(t, hi)):
            d = d.date()
            by_day.setdefault(d, []).append((published, e))
            items.append(CollectionItem(date=d, title=e["title"], text=text, source_url=e["source_url"],
                                        published_at=published))
    rows = []
    for d, regs in sorted(by_day.items()):
        regs.sort(key=lambda x: x[0])
        for n, (published, e) in enumerate(regs, start=1):     # 행사가 등록될 때마다 그날 행사 수가 n개로
            rows.append(SignalRow(date=d, store_id=store_id, signal="nearby_event", value=float(n),
                                  source_url=e["source_url"], published_at=published, kind="event"))
    return rows, items


def nearby_events(store_id: str, work_dir: Path, lo: dt.date, hi: dt.date) -> list[dict]:
    """lo~hi에 열리는 근처 서울 문화행사 목록 (agent/relevance.py가 규모·연관도를 따질 때 쓰는 모양).
    event_rows와 같은 행사만: 확인된 것, MAX_EVENT_DAYS일 이하."""
    path = Path(work_dir) / EVENTS
    out = []
    for e in json.loads(path.read_text(encoding="utf-8")) if path.exists() else []:
        if e.get("source") != "seoul_culture" or e.get("store_id") != store_id or not e.get("verified", True):
            continue
        s, t = dt.date.fromisoformat(e["start_date"]), dt.date.fromisoformat(e["end_date"])
        if (t - s).days + 1 > MAX_EVENT_DAYS or t < lo or s > hi:
            continue
        reg = e.get("published_at")
        published = (to_kst(reg).normalize() + pd.Timedelta(hours=23, minutes=59)).to_pydatetime() \
            if reg else dt.datetime.now().replace(microsecond=0)
        out.append(dict(title=e["title"], place=e.get("place", ""), category=e.get("category", ""), start=s, end=t,
                        distance_km=float(e.get("distance_m") or 0) / 1000, published_at=published, url=e.get("source_url", ""),
                        cancelled=False, snippet=None))
    return out


def signals_from_collectors(store_id: str, lo: dt.date, hi: dt.date, work_dir: Path
                            ) -> tuple[list[SignalRow], list[CollectionItem], list[str]]:
    """work_dir의 수집 결과 → (신호 줄, 행사 원문, 메모)."""
    work_dir = Path(work_dir)
    daily = pd.read_csv(work_dir / DAILY)
    events = json.loads((work_dir / EVENTS).read_text(encoding="utf-8")) if (work_dir / EVENTS).exists() else []
    rows, notes = weather_rows(store_id, daily), []
    notes.append(f"날씨 {len(rows) // 2}일")
    if (work_dir / f"{store_id}_sources.json").exists():
        ac = academic_rows(store_id, daily, events)
        rows += ac
        notes.append(f"학사일정 {len({r.date for r in ac})}일")
    else:
        notes.append("학사일정 안 씀(정보원 계획 없음: 카카오 키가 있어야 매장 근처 학교를 고름)")
    ev_rows, items = event_rows(store_id, events, lo, hi)
    rows += ev_rows
    notes.append(f"서울 문화행사 근처 {len({r.date for r in ev_rows})}일")
    return rows, items, notes
