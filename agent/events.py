"""팝업·공지 글 → nearby_event 신호 + LLM 주의 안내용 원문(collection).  (새얼 수집기에 없는 우리 추가 기능)

서울 문화행사·날씨·학사일정은 새얼 수집기(backend/collectors)가 맡는다 → agent/collectors_bridge.py
이 파일: 사람이 모은 팝업·공지 글 주소 (data/raw/{store}_event_sources.txt, 한 줄에 '주소 [공개일 YYYY-MM-DD]')
  - 글을 받아 LLM이 날짜·장소·취소 여부만 뽑는다 (구조화 출력). 판매량 숫자는 다루지 않는다.
  - 코드가 거르는 것: 근거 문장이 글에 그대로 없으면 버림, 장소를 좌표로 바꿔 NEAR_KM 밖이면 버림
  - MAX_EVENT_DAYS일 넘는 긴 팝업은 신호 없이 '여는 날' 원문만 (AI 주의 안내가 새 대형 팝업을 알릴 수 있게)
  - 공개일을 안 적으면 '지금'으로 본다 → 과거 학습에는 안 쓰이고 앞으로의 예측에만 쓰인다 (누수 방지)
"""
import datetime as dt
import hashlib
import json
import math
import os
import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

import pandas as pd
from pydantic import BaseModel

from contracts.schemas import CollectionItem, SignalRow

ROOT = Path(__file__).resolve().parents[1]
NEAR_KM = 1.0              # 매장에서 이 거리 안이면 '근처' (걸어서 15분 안팎)
MAX_EVENT_DAYS = 7         # 이보다 긴 행사는 신호로 쓰지 않는다
MAX_PAGE_CHARS = 6000      # 글은 앞 6000자까지만 LLM에 넘긴다


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """두 위치 사이 거리(km), 지구를 공으로 보는 공식 (haversine)."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _days(start: dt.date, end: dt.date, lo: dt.date, hi: dt.date) -> list[dt.date]:
    """행사 기간 중 lo~hi 안에 드는 날들."""
    return [d.date() for d in pd.date_range(max(start, lo), min(end, hi))]


def _event_rows(store_id: str, day: dt.date, value: float, url: str, published: dt.datetime) -> SignalRow:
    return SignalRow(date=day, store_id=store_id, signal="nearby_event", value=value, source_url=url,
                     published_at=published, kind="event")


# ---------------------------------------------------------------- B. 팝업·공지 글 (LLM이 날짜·장소만 뽑음)

class EventInfo(BaseModel):
    is_event: bool          # 매장 손님 수에 영향을 줄 만한 행사·팝업·공사·통제 등인가
    title: str
    start_date: dt.date | None
    end_date: dt.date | None
    place: str              # 글에 적힌 장소 그대로 (주소·건물·거리 이름)
    cancelled: bool         # 취소·연기 공지인가
    quote: str              # 날짜와 장소가 적힌 원문 문장을 그대로 복사


class EventList(BaseModel):
    events: list[EventInfo]


EXTRACT_SYSTEM = """당신은 카페·베이커리 수요 예측 서비스의 '행사 정보 정리' 담당입니다.
주어진 글에서 매장 손님 수에 영향을 줄 만한 행사(팝업스토어, 축제, 공연, 대형 모임, 도로 통제·공사 등)만 뽑습니다.
규칙:
- 날짜는 글에 적힌 것만 씁니다. '이번 주말'처럼 날짜를 확정할 수 없으면 그 행사는 뽑지 않습니다. 연도가 없으면 글의 공개일을 기준으로 정합니다.
- place는 글에 적힌 장소 이름·주소를 그대로 씁니다. 지어내지 않습니다.
- quote에는 날짜와 장소가 적힌 문장을 원문에서 글자 그대로 복사합니다.
- 판매량·손님 수 같은 숫자를 추정하지 않습니다.
- 해당하는 행사가 없으면 빈 목록을 돌려줍니다."""


class _Text(HTMLParser):
    """HTML → 글자만 (script·style 제외)."""
    def __init__(self):
        super().__init__()
        self.parts, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        self._skip += tag in ("script", "style", "noscript")

    def handle_endtag(self, tag):
        self._skip -= tag in ("script", "style", "noscript") and self._skip > 0

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def fetch_page(url: str) -> tuple[str, str]:
    """글 주소 → (제목, 본문 글자). 네이버 블로그는 휴대폰 주소로 받아야 본문이 나온다."""
    url = url.replace("://blog.naver.com", "://m.blog.naver.com")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (naeil-myeotgae prototype)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read().decode(r.headers.get_content_charset() or "utf-8", errors="replace")
    title = re.search(r"<title[^>]*>(.*?)</title>", raw, re.S | re.I)
    p = _Text()
    p.feed(raw)
    text = re.sub(r"\s+", " ", " ".join(p.parts)).strip()
    return (re.sub(r"\s+", " ", title.group(1)).strip() if title else url), text[:MAX_PAGE_CHARS]


def _extract_anthropic(model: str, user: str) -> EventList:
    import anthropic
    from ml.alerts import settings
    if "ANTHROPIC_API_KEY" not in os.environ and (key := settings().get("ANTHROPIC_API_KEY")):
        os.environ["ANTHROPIC_API_KEY"] = key
    r = anthropic.Anthropic().messages.parse(model=model, max_tokens=8000, system=EXTRACT_SYSTEM,
                                             messages=[{"role": "user", "content": user}], output_format=EventList)
    return r.parsed_output


EXTRACTORS = {"anthropic": _extract_anthropic}   # 제공자 이름 → 함수(model, user) -> EventList (ml.alerts와 같은 설정)


def extract_events(title: str, text: str, published: dt.datetime, cache_dir: Path) -> list[EventInfo]:
    """글 하나 → 행사 목록 (같은 글은 다시 부르지 않는다). 근거 문장이 글에 그대로 없으면 버린다."""
    from ml.alerts import settings
    cfg = settings()
    user = json.dumps(dict(title=title, published_at=str(published.date()), text=text), ensure_ascii=False)
    key = hashlib.sha256(f"{cfg['LLM_PROVIDER']}|{cfg['LLM_MODEL']}|{EXTRACT_SYSTEM}|{user}".encode()).hexdigest()[:16]
    cache = Path(cache_dir) / f"{key}.json"
    if cache.exists():
        result = EventList.model_validate_json(cache.read_text(encoding="utf-8"))
    else:
        result = EXTRACTORS[cfg["LLM_PROVIDER"]](cfg["LLM_MODEL"], user)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(result.model_dump_json(indent=1), encoding="utf-8")
    return [e for e in result.events
            if e.is_event and e.start_date and e.quote and e.quote in (title + "\n" + text)]


def read_sources(path: Path) -> list[tuple[str, dt.datetime | None]]:
    """'주소 [공개일]' 줄들 → [(주소, 공개 시각 또는 None)]. #으로 시작하는 줄과 빈 줄은 건너뛴다."""
    out = []
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        parts = line.split()
        if not parts or parts[0].startswith("#"):
            continue
        pub = pd.Timestamp(parts[1]).to_pydatetime() if len(parts) > 1 else None
        out.append((parts[0], pub))
    return out


def page_event_signals(store_id: str, lat: float, lon: float, sources: list[tuple[str, dt.datetime | None]],
                       start: dt.date, end: dt.date, cache_dir: Path, fetch=fetch_page, geocode=None,
                       now: dt.datetime | None = None) -> tuple[list[SignalRow], list[CollectionItem], list[str]]:
    """글 주소들 → (nearby_event 줄, 원문, 메모). 취소 공지는 value=0 줄 (가장 늦게 공개된 값이 쓰이므로 취소가 반영됨)."""
    if geocode is None:
        from agent.geocode import geocode
    now = now or dt.datetime.now().replace(microsecond=0)
    rows, items, notes = [], [], []
    for url, pub in sources:
        published = pub or now
        try:
            title, text = fetch(url)
        except Exception as e:
            notes.append(f"글을 못 받음({type(e).__name__}): {url}")
            continue
        for ev in extract_events(title, text, published, cache_dir):
            try:
                elat, elon, _ = geocode(ev.place)
            except Exception:
                notes.append(f"장소를 찾지 못해 건너뜀: {ev.place} ({url})")
                continue
            if distance_km(lat, lon, elat, elon) > NEAR_KM:
                continue
            last = ev.end_date or ev.start_date
            if (last - ev.start_date).days + 1 > MAX_EVENT_DAYS:   # 긴 팝업: 신호는 없이, 여는 날 원문만
                if start <= ev.start_date <= end:
                    items.append(CollectionItem(date=ev.start_date, title=f"[새로 엶] {ev.title or title}", text=text,
                                                source_url=url, published_at=published))
                continue
            for d in _days(ev.start_date, last, start, end):
                rows.append(_event_rows(store_id, d, 0.0 if ev.cancelled else 1.0, url, published))
                items.append(CollectionItem(date=d, title=ev.title or title, text=text, source_url=url,
                                            published_at=published))
    return rows, items, notes
