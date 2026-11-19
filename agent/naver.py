"""네이버(NAVER API HUB): 동네 뉴스·블로그 자동 검색 + 메뉴 검색량 유행.

키: 맨 위 .env의 NAVER_CLIENT_ID, NAVER_CLIENT_SECRET (2026-07-31부터 신규 키는 NAVER API HUB에서만 발급)
호출: https://naverapihub.apigw.ntruss.com, 헤더 X-NCP-APIGW-API-KEY-ID / X-NCP-APIGW-API-KEY

1. 뉴스·블로그 검색 → 행사 글 주소 목록
   "{동네} 팝업/행사/축제"를 최신순으로 찾아 글 주소와 게시 시각을 돌려준다.
   글 읽기·행사 추출·근거 대조·거리 확인은 agent/events.page_event_signals가 그대로 한다 (사람이 모은 글과 같은 길).
   게시 시각: 뉴스는 pubDate, 블로그는 작성일 23:59 (시각이 없어 보수적으로)
2. 메뉴 검색량 유행 → 메뉴별 유행 신호 trend_level (모델 입력 후보) + AI 주의 안내용 원문
   메뉴 이름으로 데이터랩 검색어 트렌드(날짜별)를 받아 날짜마다 '최근 7일 평균 ÷ 그 전 4주 평균'을 만든다.
   - 신호: 다른 신호와 똑같이, 과거 검증에서 오차를 줄일 때만 모델이 쓴다 (ml/evaluate.py)
   - 원문: 예측 날짜에 TREND_ALERT_PCT% 이상 바뀐 메뉴 → ml/alerts.py가 '유행급변' 안내 여부를 판단
"""
import datetime as dt
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from email.utils import parsedate_to_datetime

import numpy as np
import pandas as pd

from contracts.schemas import CollectionItem, SignalRow, StoreConfig
from ml import progress
from ml.llm import settings

HOST = "https://naverapihub.apigw.ntruss.com"
NEWS, BLOG, TREND = "/search/v1/news", "/search/v1/blog", "/search-trend/v1/search"
TREND_PAGE = "https://datalab.naver.com/keyword/trendSearch.naver"
WORDS = ("팝업", "행사", "축제")         # 동네 이름 뒤에 붙여 찾는 말
PER_QUERY = 10                          # 검색어마다 최신 글 몇 개
MAX_ARTICLES = 20                       # 한 번에 읽을 글 수 상한 (글마다 LLM 1번, 같은 글은 캐시)
EVENT_WORDS = re.compile(r"팝업|오픈|개최|행사|축제|전시|공연|마켓|페스티벌|플리마켓|체험|운영")
DATE_LIKE = re.compile(r"\d{1,2}\s*월\s*\d{1,2}\s*일|\d{1,2}[./]\d{1,2}|\d{1,2}일(?:부터|까지|~)")
TREND_LAG_DAYS = 2                      # D일 유행 신호는 D-2일까지의 검색량으로 만든다 (시점 규칙)
TREND_ALERT_PCT = 30.0                  # 검색량이 이만큼(%) 넘게 바뀌면 AI 주의 안내 원문으로도 넘긴다
TREND_MIN_LEVEL = 1.0                   # 그 전 4주 평균이 이보다 작으면(거의 안 찾는 말) 신호를 만들지 않음
MAX_TREND_MENUS = 20                    # 판매량 상위 메뉴만 (메뉴 하나에 요청 한 번)
RETRIES = 3                             # 요청이 몰려 잠깐 막히면(429·5xx) 쉬었다가 다시 시도하는 횟수


def _keys() -> dict[str, str]:
    cfg = settings()
    cid, secret = cfg.get("NAVER_CLIENT_ID"), cfg.get("NAVER_CLIENT_SECRET")
    if not cid or not secret:
        raise RuntimeError(".env에 NAVER_CLIENT_ID·NAVER_CLIENT_SECRET이 없음")
    return {"X-NCP-APIGW-API-KEY-ID": cid, "X-NCP-APIGW-API-KEY": secret}


def has_keys() -> bool:
    try:
        _keys()
        return True
    except RuntimeError:
        return False


def _request(path: str, params: dict | None = None, body: dict | None = None) -> dict:
    url = HOST + path + ("?" + urllib.parse.urlencode(params) if params else "")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = dict(_keys(), **({"Content-Type": "application/json"} if body is not None else {}))
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or attempt == RETRIES - 1:
                raise
            time.sleep(2 * (attempt + 1))              # 2초, 4초 쉬고 다시


# ---------------------------------------------------------------- 1. 뉴스·블로그

def area_keywords(store: StoreConfig, station: str | None = None) -> list[str]:
    """근처 소식을 검색할 동네 이름. 순서: 매장 설정의 area_keywords → 가장 가까운 역 이름(station) → 주소에서 뽑은 말.
    역 이름 하나만 쓰는 이유: 재 보니 '신촌' 하나로 찾을 때 근처 행사가 가장 많이 나왔다. 주소에서 뽑은 '서대문'·'연세'는
    구청 소식·병원 학술행사가 섞이고, 말을 여럿 쓰면 읽을 글 MAX_ARTICLES개 안에서 좋은 글이 밀려난다 (ml/REVIEW.md E).
    주소에서 뽑기: 도로·구 이름 ('서울숲2길' → '서울숲', '성동구' → '성동')."""
    if store.area_keywords:
        return list(store.area_keywords)
    if station:
        return [station]
    out = []
    for tok in (store.address or "").split():
        m = re.fullmatch(r"(.+?)\d*(?:길|로)", tok) or re.fullmatch(r"(.+?)(?:구|동)", tok)
        if m and len(m.group(1)) >= 2 and m.group(1) not in out:
            out.append(m.group(1))
    return out[:2]


def _clean(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").replace("&quot;", '"').replace("&amp;", "&").strip()


def news_sources(areas: list[str], search=None, now: dt.datetime | None = None
                 ) -> tuple[list[tuple[str, dt.datetime]], list[str]]:
    """동네 이름 × WORDS로 뉴스(최신순)·블로그(정확도순)를 검색 → [(글 주소, 게시 시각)] (중복 제거, 최신 MAX_ARTICLES개).
    게시 시각은 지금(읽은 시각)을 넘지 않는다: 지금 읽었다면 이미 공개된 것이므로 (블로그 '오늘 23:59'를 지금으로)."""
    now = now or dt.datetime.now().replace(microsecond=0)
    sort = {NEWS: "date", BLOG: "sim"}                 # 최신 블로그는 오늘 쓴 후기 위주라 정확도순이 행사 글을 더 찾음
    search = search or (lambda path, q: _request(path, dict(query=q, display=PER_QUERY, sort=sort[path]))["items"])
    found: dict[str, dt.datetime] = {}
    score: dict[str, int] = {}                     # 제목·요약에 행사 단어·날짜가 있으면 먼저 읽는다
    notes = []
    for area in areas:
        for word in WORDS:
            q = f"{area} {word}"
            for kind, path in (("뉴스", NEWS), ("블로그", BLOG)):
                try:
                    items = search(path, q)
                except Exception as e:
                    notes.append(f"네이버 {kind} 검색 실패({q}: {type(e).__name__})")
                    continue
                for it in items:
                    if kind == "뉴스":
                        url = it.get("originallink") or it.get("link")
                        t = parsedate_to_datetime(it["pubDate"])
                        published = t.astimezone(dt.timezone(dt.timedelta(hours=9))).replace(tzinfo=None)
                    else:
                        url = it.get("link")
                        published = dt.datetime.strptime(it["postdate"], "%Y%m%d") + dt.timedelta(hours=23, minutes=59)
                    published = min(published, now)
                    blurb = _clean(it.get("title", "")) + " " + _clean(it.get("description", ""))
                    s = bool(EVENT_WORDS.search(blurb)) + bool(DATE_LIKE.search(blurb))
                    if url and (url not in found or published < found[url]):
                        found[url] = published
                    if url:
                        score[url] = max(score.get(url, 0), s)
    useful = [(u, t) for u, t in found.items() if score.get(u, 0) > 0]      # 행사 단어도 날짜도 없는 글은 안 읽음
    newest = sorted(useful, key=lambda x: (score[x[0]], x[1]), reverse=True)[:MAX_ARTICLES]
    notes.append(f"네이버 검색 글 {len(found)}개 중 행사 글 {len(useful)}개, {len(newest)}개 읽음 ({', '.join(areas)})")
    return newest, notes


# ---------------------------------------------------------------- 2. 메뉴 검색량 유행

def menu_keyword(menu: str) -> str:
    """POS 메뉴 이름 → 검색어. 아이스/핫 표기·괄호를 뗀다 ('아메리카노(ICE)' → '아메리카노')."""
    s = re.sub(r"\((?:ice|iced|hot)\)|아이스|따뜻한|\b(?:ice|iced|hot)\b", "", menu, flags=re.I)
    return " ".join(re.sub(r"[()\[\]]", " ", s).split())


def fetch_trend(menus: list[str], start: dt.date, end: dt.date, post=None) -> dict[str, pd.Series]:
    """메뉴 → 날짜별 검색량 Series (start~end, 그 검색어가 가장 많이 찾아진 날 = 100인 상대값).
    - 검색어 하나당 요청 하나: 여러 검색어를 한 요청에 넣으면 가장 많이 찾는 말 기준으로 눌려 작은 검색어가 뭉개진다.
    - 검색어가 같은 메뉴(아이스·핫)는 한 번만 받는다.
    - 가운데 빠진 날은 0(아무도 안 찾음), 아직 집계되지 않은 끝쪽 날짜는 빈 값(NaN).
    - 요청이 실패한 검색어의 메뉴는 결과에서 빠진다 (나머지 메뉴는 계속)."""
    post = post or (lambda body: _request(TREND, body=body))
    days = pd.date_range(start, end)
    by_keyword: dict[str, pd.Series | None] = {}
    out = {}
    for menu in menus:
        kw = menu_keyword(menu)
        if not kw:
            continue
        if kw not in by_keyword:
            try:
                res = post({"startDate": start.isoformat(), "endDate": end.isoformat(), "timeUnit": "date",
                            "keywordGroups": [{"groupName": kw, "keywords": [kw]}]})
            except Exception:
                by_keyword[kw] = None
                continue
            data = (res.get("results") or [{}])[0].get("data", [])
            got = pd.Series({pd.Timestamp(d["period"]): float(d["ratio"]) for d in data}, dtype=float)
            full = got.reindex(days, fill_value=0.0)
            full[days > got.index.max() if len(got) else days >= days[0]] = np.nan
            by_keyword[kw] = full
        if by_keyword[kw] is not None:
            out[menu] = by_keyword[kw]
    return out


def trend_level(searches: pd.Series, until: dt.date) -> pd.Series:
    """날짜 D마다 '최근 7일 평균 검색량 ÷ 그 전 28일 평균 검색량' (1 = 평소와 같음, 1.5 = 50% 늘어남).
    ★ D일 값은 D-2일까지의 검색량만 쓴다 (TREND_LAG_DAYS): D일 예측을 내는 D-1일 저녁에 확실히 볼 수 있는 것은
      그 전날(D-2)까지의 집계이므로.  최근 7일 = D-8 ~ D-2,  그 전 28일 = D-36 ~ D-9.
    평소 검색량이 TREND_MIN_LEVEL보다 작은 말(거의 안 찾는 말)은 비율이 크게 튀므로 빈 값으로 둔다."""
    s = searches.reindex(pd.date_range(searches.index.min(), until))
    recent = s.rolling(7, min_periods=4).mean().shift(TREND_LAG_DAYS)
    before = s.rolling(28, min_periods=14).mean().shift(TREND_LAG_DAYS + 7)
    return (recent / before).where(before >= TREND_MIN_LEVEL)


def menu_trend(store_id: str, menus: list[str], start: dt.date, target: dt.date, post=None,
               today: dt.date | None = None) -> tuple[list[SignalRow], list[CollectionItem], list[str]]:
    """판매량 상위 메뉴의 검색량 → (유행 신호 줄, 주의 안내 원문, 메모).
      신호 줄: 메뉴마다 start~target의 날짜별 trend_level (모델 입력 후보. 검증에서 도움이 될 때만 채택됨)
      원문:   예측 날짜(target)에 검색량이 TREND_ALERT_PCT% 넘게 바뀐 메뉴만 한 건씩 (AI 주의 안내의 재료)
    공개 시각은 D-1일 09:00으로 적는다 (D-2일까지의 집계가 나온 뒤)."""
    today = today or dt.date.today()
    first = start - dt.timedelta(days=TREND_LAG_DAYS + 35)                       # 첫날의 '그 전 28일'까지
    last = min(target - dt.timedelta(days=TREND_LAG_DAYS), today - dt.timedelta(days=1))
    menus = menus[:MAX_TREND_MENUS]
    series = fetch_trend(menus, first, last, post)
    rows, items, changed, latest = [], [], [], []
    for menu, searches in series.items():
        level = trend_level(searches, target)[pd.Timestamp(start):].dropna()
        for day, value in level.items():
            published = (day - pd.Timedelta(days=1) + pd.Timedelta(hours=9)).to_pydatetime()
            rows.append(SignalRow(date=day.date(), store_id=store_id, signal="trend_level", menu=menu,
                                  value=round(float(value), 3), source_url=TREND_PAGE, published_at=published,
                                  kind="observed"))
        now_level = level.get(pd.Timestamp(target))
        if now_level is not None:
            latest.append((menu, round((float(now_level) - 1) * 100)))
        if now_level is None or abs(now_level - 1) * 100 < TREND_ALERT_PCT:
            continue
        pct = (now_level - 1) * 100
        a, b = target - dt.timedelta(days=TREND_LAG_DAYS + 6), target - dt.timedelta(days=TREND_LAG_DAYS)
        text = (f"네이버 데이터랩 검색어 트렌드에서 '{menu_keyword(menu)}' 검색량은 최근 7일({a}~{b}) 평균이 "
                f"그 전 4주 평균보다 {abs(pct):.0f}% {'늘었다' if pct > 0 else '줄었다'}.")
        items.append(CollectionItem(date=target, title=f"검색량 변화: {menu}", text=text, source_url=TREND_PAGE,
                                    published_at=dt.datetime.combine(target - dt.timedelta(days=1), dt.time(9))))
        changed.append(f"{menu} {pct:+.0f}%")
    if rows:                                # 화면: 가져온 기간 전체(모델이 배우는 재료)를 먼저, 그다음 메뉴별 요즘 변화
        days = {r.date for r in rows}
        progress.emit("trend_span", menus=len({r.menu for r in rows}), days=len(days), first=min(days), last=max(days))
    for menu, pct in latest:
        progress.emit("trend", menu=menu, pct=pct)
    note = (f"메뉴 검색량 {len(series)}개" + (f"(요청 실패 {len(menus) - len(series)}개)" if len(series) < len(menus) else "")
            + f" → 유행 신호 {len({r.menu for r in rows})}개 메뉴"
            + (f", 크게 바뀐 메뉴: {', '.join(changed)}" if changed else ", 크게 바뀐 메뉴 없음"))
    return rows, items, [note]
