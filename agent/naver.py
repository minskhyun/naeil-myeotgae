"""네이버(NAVER API HUB): 동네 뉴스·블로그 자동 검색 + 메뉴 검색량 유행.

키: 맨 위 .env의 NAVER_CLIENT_ID, NAVER_CLIENT_SECRET (2026-07-31부터 신규 키는 NAVER API HUB에서만 발급)
호출: https://naverapihub.apigw.ntruss.com, 헤더 X-NCP-APIGW-API-KEY-ID / X-NCP-APIGW-API-KEY

1. 뉴스·블로그 검색 → 행사 글 주소 목록
   "{동네} 팝업/행사/축제"를 최신순으로 찾아 글 주소와 게시 시각을 돌려준다.
   글 읽기·행사 추출·근거 대조·거리 확인은 agent/events.page_event_signals가 그대로 한다 (사람이 모은 글과 같은 길).
   게시 시각: 뉴스는 pubDate, 블로그는 작성일 23:59 (시각이 없어 보수적으로)
2. 메뉴 검색량 유행 → LLM 주의 안내용 원문 (모델 입력으로는 아직 쓰지 않음, 11/17 결정 A안)
   메뉴 이름으로 데이터랩 검색어 트렌드(날짜별)를 받아 '최근 7일 평균'을 '그 전 4주 평균'과 비교,
   TREND_ALERT_PCT% 이상 바뀌면 그 사실을 원문 한 건으로 만든다 → ml/alerts.py가 '유행급변' 안내 여부를 판단.
"""
import datetime as dt
import json
import re
import urllib.parse
import urllib.request
from email.utils import parsedate_to_datetime

import pandas as pd

from contracts.schemas import CollectionItem

HOST = "https://naverapihub.apigw.ntruss.com"
NEWS, BLOG, TREND = "/search/v1/news", "/search/v1/blog", "/search-trend/v1/search"
TREND_PAGE = "https://datalab.naver.com/keyword/trendSearch.naver"
WORDS = ("팝업", "행사", "축제")         # 동네 이름 뒤에 붙여 찾는 말
PER_QUERY = 10                          # 검색어마다 최신 글 몇 개
MAX_ARTICLES = 20                       # 한 번에 읽을 글 수 상한 (글마다 LLM 1번, 같은 글은 캐시)
EVENT_WORDS = re.compile(r"팝업|오픈|개최|행사|축제|전시|공연|마켓|페스티벌|플리마켓|체험|운영")
DATE_LIKE = re.compile(r"\d{1,2}\s*월\s*\d{1,2}\s*일|\d{1,2}[./]\d{1,2}|\d{1,2}일(?:부터|까지|~)")
TREND_ALERT_PCT = 30.0                  # 검색량이 이만큼(%) 넘게 바뀌면 원문으로 넘긴다
TREND_MIN_LEVEL = 1.0                   # 그 전 4주 평균이 이보다 작으면(거의 안 찾는 말) 건너뜀
MAX_TREND_MENUS = 10                    # 판매량 상위 메뉴만 (요청 하나에 키워드 묶음 5개까지)


def _keys() -> dict[str, str]:
    from ml.alerts import settings
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
    with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


# ---------------------------------------------------------------- 1. 뉴스·블로그

def area_keywords(info: dict) -> list[str]:
    """매장 설정의 area_keywords, 없으면 주소에서 도로·구 이름을 뽑는다 ('서울숲2길' → '서울숲', '성동구' → '성동')."""
    if info.get("area_keywords"):
        return list(info["area_keywords"])
    out = []
    for tok in str(info.get("address", "")).split():
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
    """메뉴 → 날짜별 검색량(상대값) Series. 요청 하나에 5개씩."""
    post = post or (lambda body: _request(TREND, body=body))
    out = {}
    for i in range(0, len(menus), 5):
        groups = [{"groupName": m, "keywords": [menu_keyword(m)]} for m in menus[i:i + 5] if menu_keyword(m)]
        if not groups:
            continue
        res = post({"startDate": start.isoformat(), "endDate": end.isoformat(), "timeUnit": "date",
                    "keywordGroups": groups})
        for r in res.get("results", []):
            s = pd.Series({pd.Timestamp(d["period"]): float(d["ratio"]) for d in r.get("data", [])}, dtype=float)
            out[r["title"]] = s.reindex(pd.date_range(start, end), fill_value=0.0)
    return out


def trend_items(menus: list[str], target: dt.date, today: dt.date | None = None, post=None,
                now: dt.datetime | None = None) -> tuple[list[CollectionItem], list[str]]:
    """메뉴마다 '최근 7일(어제까지) 평균' vs '그 전 28일 평균' → 많이 바뀐 메뉴만 원문 한 건씩 (날짜 = 예측 날짜)."""
    today = today or dt.date.today()
    end = today - dt.timedelta(days=1)
    start = end - dt.timedelta(days=34)
    now = now or dt.datetime.now().replace(microsecond=0)
    series = fetch_trend(menus[:MAX_TREND_MENUS], start, end, post)
    items, changed = [], []
    for menu, s in series.items():
        recent, before = s.iloc[-7:].mean(), s.iloc[-35:-7].mean()
        if before < TREND_MIN_LEVEL:
            continue
        pct = (recent / before - 1) * 100
        if abs(pct) < TREND_ALERT_PCT:
            continue
        kw = menu_keyword(menu)
        a, b = s.index[-7].date(), s.index[-1].date()
        text = (f"네이버 데이터랩 검색어 트렌드에서 '{kw}' 검색량은 최근 7일({a}~{b}) 평균이 "
                f"그 전 4주 평균보다 {abs(pct):.0f}% {'늘었다' if pct > 0 else '줄었다'}.")
        items.append(CollectionItem(date=target, title=f"검색량 변화: {menu}", text=text, source_url=TREND_PAGE,
                                    published_at=now))
        changed.append(f"{menu} {pct:+.0f}%")
    note = f"메뉴 검색량 {len(series)}개 확인" + (f", 크게 바뀐 메뉴: {', '.join(changed)}" if changed else ", 크게 바뀐 메뉴 없음")
    return items, [note]
