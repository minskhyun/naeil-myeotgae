"""매장 근처 행사 → nearby_event 신호 + LLM 주의 안내용 원문(collection).

두 가지 출처
  A. 서울 열린데이터광장 '문화행사 정보' (.env의 SEOUL_DATA_KEY)
     - 이미 정리된 자료(날짜·장소·좌표·등록일)라 LLM이 필요 없다.
     - 매장에서 NEAR_KM 안, 기간이 MAX_EVENT_DAYS일 이하인 행사만 숫자 신호로 (긴 전시·상설 팝업은 '그날의 행사'가 아님)
     - 긴 행사도 '여는 날'에는 원문으로 넘긴다 → AI 주의 안내가 "근처에 큰 팝업이 새로 열림"을 알릴 수 있게
     - 공개 시각 = 등록일(RGSTDATE) 23:59  (정확한 시각을 몰라 보수적으로 그날 끝으로 본다)
  B. 사람이 모은 팝업·공지 글 주소 (data/raw/{store}_event_sources.txt, 한 줄에 '주소 [공개일 YYYY-MM-DD]')
     - 글을 받아 LLM이 날짜·장소·취소 여부만 뽑는다 (구조화 출력). 판매량 숫자는 다루지 않는다.
     - 코드가 거르는 것: 근거 문장이 글에 그대로 없으면 버림, 장소를 좌표로 바꿔 NEAR_KM 밖이면 버림
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
SEOUL_URL = "http://openapi.seoul.go.kr:8088/{key}/json/culturalEventInfo/{a}/{b}/"
SEOUL_SOURCE = "https://culture.seoul.go.kr"
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


# ---------------------------------------------------------------- A. 서울 문화행사 정보

def fetch_seoul_events(key: str) -> list[dict]:
    """문화행사 전체 (1000건씩 나눠 받는다)."""
    rows, a = [], 1
    while True:
        url = SEOUL_URL.format(key=urllib.parse.quote(key), a=a, b=a + 999)
        with urllib.request.urlopen(url, timeout=60) as r:
            body = json.loads(r.read().decode("utf-8"))
        data = body.get("culturalEventInfo")
        if data is None:                                   # 키 오류 등은 RESULT만 온다
            raise RuntimeError(f"서울 문화행사 API 오류: {body.get('RESULT', body)}")
        rows += data.get("row", [])
        if a + 999 >= int(data["list_total_count"]):
            return rows
        a += 1000


def seoul_event_signals(store_id: str, lat: float, lon: float, events: list[dict], start: dt.date, end: dt.date
                        ) -> tuple[list[SignalRow], list[CollectionItem]]:
    """매장 근처의 짧은 행사 → 날마다 nearby_event=1 (같은 날 여러 행사여도 한 줄) + 행사마다 원문."""
    first: dict[dt.date, tuple[dt.datetime, str]] = {}      # 날짜 → 가장 먼저 공개된 행사 (공개 시각, 출처)
    items = []
    for e in events:
        try:
            elat, elon = float(e["LAT"]), float(e["LOT"])
            s, t = pd.Timestamp(e["STRTDATE"]).date(), pd.Timestamp(e["END_DATE"]).date()
            published = pd.Timestamp(e["RGSTDATE"]).normalize() + pd.Timedelta(hours=23, minutes=59)
        except (KeyError, ValueError, TypeError):
            continue
        # 좌표가 뒤바뀌어 들어온 행(위도 자리에 경도)도 있어 범위로 바로잡는다
        if elat > 90:
            elat, elon = elon, elat
        if distance_km(lat, lon, elat, elon) > NEAR_KM:
            continue
        url = e.get("ORG_LINK") or e.get("HMPG_ADDR") or SEOUL_SOURCE
        text = (f"{e.get('TITLE', '')}. 장소: {e.get('PLACE', '')} ({e.get('GUNAME', '')}). 기간: {e.get('DATE', '')}. "
                f"분야: {e.get('CODENAME', '')}. 대상: {e.get('USE_TRGT', '')}. 요금: {e.get('USE_FEE', '')}. "
                f"{e.get('PROGRAM', '')} {e.get('ETC_DESC', '')}").strip()
        if (t - s).days + 1 > MAX_EVENT_DAYS:             # 긴 행사: 신호는 없이, 여는 날 원문만
            if start <= s <= end:
                items.append(CollectionItem(date=s, title=f"[새로 엶] {e.get('TITLE', '행사')}", text=text,
                                            source_url=url, published_at=published.to_pydatetime()))
            continue
        days = _days(s, t, start, end)
        if not days:
            continue
        for d in days:
            if d not in first or published < first[d][0]:
                first[d] = (published.to_pydatetime(), url)
            items.append(CollectionItem(date=d, title=e.get("TITLE", "행사"), text=text, source_url=url,
                                        published_at=published.to_pydatetime()))
    rows = [_event_rows(store_id, d, 1.0, url, pub) for d, (pub, url) in sorted(first.items())]
    return rows, items


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


# ---------------------------------------------------------------- 한 번에

def collect_events(store_id: str, lat: float, lon: float, start: dt.date, end: dt.date,
                   seoul_key: str | None = None, sources_path: Path | None = None
                   ) -> tuple[list[SignalRow], list[CollectionItem], list[str]]:
    """A + B를 모은다. 출처마다 실패해도 나머지는 계속한다. 메모는 실행 기록에 남길 말."""
    rows, items, notes = [], [], []
    if seoul_key:
        try:
            r, i = seoul_event_signals(store_id, lat, lon, fetch_seoul_events(seoul_key), start, end)
            rows, items = rows + r, items + i
            notes.append(f"서울 문화행사 근처 {len({x.date for x in r})}일")
        except Exception as e:
            notes.append(f"서울 문화행사 실패({type(e).__name__}: {str(e)[:60]})")
    else:
        notes.append("서울 문화행사 건너뜀(.env에 SEOUL_DATA_KEY 없음)")
    if sources_path and Path(sources_path).exists():
        r, i, n = page_event_signals(store_id, lat, lon, read_sources(sources_path), start, end,
                                     ROOT / "data" / "raw" / "llm_cache_events")
        rows, items, notes = rows + r, items + i, notes + n
        notes.append(f"글 {len(read_sources(sources_path))}개에서 행사 {len({x.date for x in r})}일")
    # 같은 날짜에 줄이 여럿이면 features가 '가장 늦게 공개된 값'을 쓴다 → 그대로 둔다 (취소 공지가 이기도록)
    return rows, items, notes
