"""agent/naver.py 테스트 (인터넷 없이): 동네 이름, 메뉴 검색어, 뉴스·블로그 게시 시각·중복, 메뉴별 유행 신호."""
import datetime as dt

import pandas as pd
import pytest

from agent import naver
from contracts.schemas import StoreConfig


def test_area_keywords():
    assert naver.area_keywords(StoreConfig(store_id="s", address="서울 성동구 서울숲2길 12-7")) == ["성동", "서울숲"]
    assert naver.area_keywords(StoreConfig(store_id="s", address="x", area_keywords=["성수", "서울숲"])) == ["성수", "서울숲"]


def test_menu_keyword():
    assert [naver.menu_keyword(m) for m in ["아메리카노(ICE)", "아이스 카페라떼", "소금빵", "카페라떼(HOT)"]] == \
        ["아메리카노", "카페라떼", "소금빵", "카페라떼"]


def test_news_sources_times_dedupe_and_order(monkeypatch):
    monkeypatch.setattr(naver, "WORDS", ("팝업",))
    ev = dict(title="성수 팝업 오픈", description="11월 20일부터")                              # 행사 단어 + 날짜 → 2점
    news = [dict(originallink="https://n/1", link="x", pubDate="Mon, 16 Nov 2026 21:56:00 +0900", **ev),
            dict(originallink="https://n/2", link="y", pubDate="Mon, 16 Nov 2026 03:00:00 +0000", **ev),  # UTC → KST 12:00
            dict(originallink="https://n/3", link="z", pubDate="Mon, 16 Nov 2026 10:00:00 +0900",
                 title="주가 동향", description="오늘 시장")]                                      # 행사 글 아님 → 안 읽음
    blog = [dict(link="https://b/1", postdate="20261110", **ev), dict(link="https://n/1", postdate="20261101", **ev)]

    def search(path, q):
        return news if path == naver.NEWS else blog
    found, notes = naver.news_sources(["서울숲"], search=search)
    assert found == [("https://n/2", dt.datetime(2026, 11, 16, 12, 0)),       # UTC 03시 → 한국 12시, 최신 글부터
                     ("https://b/1", dt.datetime(2026, 11, 10, 23, 59)),      # 블로그는 작성일 23:59
                     ("https://n/1", dt.datetime(2026, 11, 1, 23, 59))]       # 같은 글은 더 이른 게시 시각으로


def test_trend_level_uses_searches_only_up_to_two_days_before():
    """검색량이 11/10부터 10 → 20으로 뛰었을 때: 11/11(D)에는 아직 모르고(D-2 = 11/9까지만 봄), 11/12부터 반영된다."""
    days = pd.date_range("2026-10-01", "2026-11-16")
    searches = pd.Series([10.0 if d < pd.Timestamp("2026-11-10") else 20.0 for d in days], index=days)
    level = naver.trend_level(searches, dt.date(2026, 11, 18))
    assert level["2026-11-11"] == pytest.approx(1.0)                          # 최근 7일 = 11/3~11/9, 모두 10
    assert level["2026-11-12"] == pytest.approx((6 * 10 + 20) / 7 / 10)       # 최근 7일 = 11/4~11/10, 하루만 20
    assert level["2026-11-18"] == pytest.approx(2.0)                          # 최근 7일 = 11/10~11/16, 모두 20
    assert level.index.max() == pd.Timestamp("2026-11-18")                    # 예측 날짜까지 값이 있다


def test_menu_trend_makes_signals_and_flags_big_changes():
    calls = []

    def post(body):                                                           # 11/10부터 검색량이 바뀌는 가짜 응답
        kw = body["keywordGroups"][0]["keywords"][0]
        calls.append(kw)
        before, recent = {"소금빵": (10, 15), "베이글": (10, 11), "단팥빵": (0.5, 5), "아메리카노": (10, 10)}[kw]
        days = pd.date_range(body["startDate"], body["endDate"])
        return {"results": [dict(title=kw, data=[dict(period=str(d.date()), ratio=before if d < pd.Timestamp("2026-11-10")
                                                      else recent) for d in days])]}

    menus = ["소금빵", "베이글", "단팥빵", "아메리카노(ICE)", "아메리카노(HOT)"]
    rows, items, notes = naver.menu_trend("s", menus, dt.date(2026, 11, 10), dt.date(2026, 11, 18), post=post,
                                          today=dt.date(2026, 11, 17))
    assert calls.count("아메리카노") == 1                                      # 아이스·핫은 검색어가 같아 한 번만 받음
    assert {r.menu for r in rows} == {"소금빵", "베이글", "아메리카노(ICE)", "아메리카노(HOT)"}   # 단팥빵은 거의 안 찾는 말
    last = next(r for r in rows if r.menu == "소금빵" and r.date == dt.date(2026, 11, 18))
    assert (last.signal, last.value, last.kind) == ("trend_level", 1.5, "observed")
    assert last.published_at == dt.datetime(2026, 11, 17, 9, 0)               # D-1일 아침 (예측 시각보다 앞)
    assert [i.title for i in items] == ["검색량 변화: 소금빵"]                 # +50%만 주의 안내로 (베이글 +10%)
    assert "50% 늘었다" in items[0].text and items[0].date == dt.date(2026, 11, 18)
    assert "소금빵 +50%" in notes[0]


def test_place_queries_try_address_and_names_first():
    from agent.geocode import place_queries
    q = place_queries("서울 성수동 '플레임그라운드(Flameground by BURGER KING)'")
    assert "플레임그라운드" in q and q.index("플레임그라운드") < q.index("서울 성수동 플레임그라운드")
    assert place_queries("한섬 EQL 성수, 서울 성동구 연무장15길 11")[0] == "서울 성동구 연무장15길 11"
