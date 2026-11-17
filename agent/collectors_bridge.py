"""새얼 수집기(backend/collectors) 실행 + 결과를 예측 엔진 입력으로 바꾸기.

    새얼 수집기: python -m collectors.run_all (backend/ 에서)
      → backend/data/external_daily.csv  날짜당 한 줄 (날씨 관측·예보, 학사 기간 수, 근처 행사 수)
      → backend/data/events.json         행사·학사일정 목록 (출처, 게시 시각, 매장과의 거리)
    이 파일이 하는 일: 위 두 파일 → SignalRow(시점 규칙용 공개 시각 포함) + CollectionItem(LLM 주의 안내 원문)

공개 시각을 붙이는 규칙
  - 날씨 관측값: '전날 17:10 예보'처럼 (실제 예보가 아님 → source_url 끝에 OBSERVED_PROXY, 결과를 말할 때 밝힐 것)
  - 날씨 예보: 새얼이 적은 발표 시각(weather_issued_at)
  - 학사 기간(exam_period·vacation·festival): 학사일정은 학기 전에 공개되므로 그 해 1월 1일 공개로 본다
    ※ 정보원 계획(어느 학교를 쓸지)이 없으면 새얼 수집기가 신촌 3개 대학을 모두 세므로, 계획이 없으면 쓰지 않는다
  - 근처 행사(nearby_event): events.json의 서울 문화행사를 다시 세어, 등록될 때마다 그날 행사 수를 한 줄씩
    (등록일 23:59 공개로 본다, 보수적). 예측 시각에는 그때까지 등록된 행사 수가 쓰인다
"""
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

from contracts.schemas import CollectionItem, SignalRow

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
DAILY = BACKEND / "data" / "external_daily.csv"
EVENTS = BACKEND / "data" / "events.json"
STORES = BACKEND / "collectors" / "stores.json"
PLAN_DIR = BACKEND / "data" / "stores"

OBSERVED_PROXY = "#관측값을-예보-대신-사용"     # 이 표시가 붙은 신호는 실제 예보가 아니다 (run.py가 줄 수를 알려 줌)
KMA_OBSERVED = "https://data.kma.go.kr"
KMA_FORECAST = "https://www.data.go.kr/data/15084084/openapi.do"
ACADEMIC_COLS = ["exam_period", "vacation", "festival"]
MAX_EVENT_DAYS = 14                            # 새얼 수집기와 같은 기준 (이보다 긴 상설 전시는 신호가 안 됨)


# ---------------------------------------------------------------- 수집기 실행

def ensure_store(store_id: str, info: dict) -> None:
    """새얼 수집기의 매장 목록(stores.json)에 이 매장을 넣거나 고친다 (이름·주소·좌표)."""
    stores = json.loads(STORES.read_text(encoding="utf-8"))
    entry = dict(store_id=store_id, name=info.get("name", store_id), category=info.get("category", "카페"),
                 address=info.get("address", ""), lat=info.get("lat"), lon=info.get("lon"))
    stores = [s for s in stores if s["store_id"] != store_id] + [entry]
    STORES.write_text(json.dumps(stores, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_collectors(store_id: str, start: dt.date, end: dt.date) -> tuple[bool, list[str]]:
    """python -m collectors.run_all 을 backend/에서 실행. 돌려주는 값: (성공 여부, 출력 마지막 몇 줄)."""
    DAILY.unlink(missing_ok=True)          # 실패했을 때 다른 매장의 옛 결과를 쓰지 않도록 먼저 지운다
    cmd = [sys.executable, "-m", "collectors.run_all", "--store", store_id,
           "--start", start.isoformat(), "--end", end.isoformat()]
    proc = subprocess.run(cmd, cwd=BACKEND, capture_output=True, text=True, encoding="utf-8", errors="replace")
    lines = [l for l in (proc.stdout + proc.stderr).splitlines() if l.strip()]
    return proc.returncode == 0 and DAILY.exists(), lines[-6:]


# ---------------------------------------------------------------- 결과 → 신호

def _kst(t) -> dt.datetime:
    t = pd.Timestamp(t)
    return (t.tz_convert("Asia/Seoul").tz_localize(None) if t.tzinfo is not None else t).to_pydatetime()


def weather_rows(store_id: str, daily: pd.DataFrame) -> list[SignalRow]:
    rows = []
    for r in daily.itertuples():
        if pd.isna(r.temp_mean) or not isinstance(r.weather_kind, str):
            continue
        day = pd.Timestamp(r.date)
        if r.weather_kind == "forecast" and isinstance(r.weather_issued_at, str):
            published, url = _kst(r.weather_issued_at), KMA_FORECAST
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
        published = (pd.Timestamp(_kst(reg)).normalize() + pd.Timedelta(hours=23, minutes=59)).to_pydatetime() \
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


def signals_from_collectors(store_id: str, lo: dt.date, hi: dt.date, daily_path: Path = DAILY,
                            events_path: Path = EVENTS, plan_dir: Path = PLAN_DIR
                            ) -> tuple[list[SignalRow], list[CollectionItem], list[str]]:
    daily = pd.read_csv(daily_path)
    events = json.loads(Path(events_path).read_text(encoding="utf-8")) if Path(events_path).exists() else []
    rows, notes = weather_rows(store_id, daily), []
    notes.append(f"날씨 {len(rows) // 2}일")
    if (Path(plan_dir) / f"{store_id}_sources.json").exists():
        ac = academic_rows(store_id, daily, events)
        rows += ac
        notes.append(f"학사일정 {len({r.date for r in ac})}일")
    else:
        notes.append("학사일정 안 씀(정보원 계획 없음: 카카오 키가 있어야 매장 근처 학교를 고름)")
    ev_rows, items = event_rows(store_id, events, lo, hi)
    rows += ev_rows
    notes.append(f"서울 문화행사 근처 {len({r.date for r in ev_rows})}일")
    return rows, items, notes


# ---------------------------------------------------------------- 한 번에 (run.py가 부름)

def collect_all(store_id: str, info: dict, start: dt.date, end: dt.date, sources_path: Path | None = None
                ) -> tuple[list[SignalRow], list[CollectionItem], list[str]]:
    """새얼 수집기 + 우리 추가 기능(기념일, 팝업 글 LLM 추출). 출처마다 실패해도 나머지는 계속."""
    from agent.events import page_event_signals, read_sources
    from agent.special_days import special_day_signals
    rows, items, notes = [], [], []
    ensure_store(store_id, info)
    yesterday = dt.date.today() - dt.timedelta(days=1)
    ok, tail = run_collectors(store_id, start, yesterday)
    if ok:
        r, i, n = signals_from_collectors(store_id, start, end)
        rows, items, notes = rows + r, items + i, notes + n
    else:
        notes.append("새얼 수집기 실패 → 날씨·학사일정·서울 행사 없이 진행: " + " / ".join(tail[-2:]))
    rows += special_day_signals(store_id, start, end)
    if sources_path and Path(sources_path).exists():
        r, i, n = page_event_signals(store_id, info["lat"], info["lon"], read_sources(sources_path), start, end,
                                     ROOT / "data" / "raw" / "llm_cache_events")
        rows, items, notes = rows + r, items + i, notes + n
        notes.append(f"팝업 글에서 행사 {len({x.date for x in r})}일")
    return rows, items, notes
