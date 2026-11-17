"""agent/naver.py 테스트 (인터넷 없이): 동네 이름, 메뉴 검색어, 뉴스·블로그 게시 시각·중복, 검색량 변화 계산."""
import datetime as dt

from agent import naver


def test_area_keywords():
    assert naver.area_keywords({"address": "서울 성동구 서울숲2길 12-7"}) == ["성동", "서울숲"]
    assert naver.area_keywords({"address": "x", "area_keywords": ["성수", "서울숲"]}) == ["성수", "서울숲"]


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


def test_trend_items_flags_big_changes_only():
    today = dt.date(2026, 11, 17)
    days = [today - dt.timedelta(days=k) for k in range(35, 0, -1)]            # 10/13 ~ 11/16 (35일)

    def series(before, recent):
        return [dict(period=d.isoformat(), ratio=before if i < 28 else recent) for i, d in enumerate(days)]

    def post(body):
        data = {"소금빵": series(10, 15), "베이글": series(10, 11), "단팥빵": series(0.5, 5)}
        return {"results": [dict(title=g["groupName"], data=data[g["groupName"]]) for g in body["keywordGroups"]]}
    items, notes = naver.trend_items(["소금빵", "베이글", "단팥빵"], dt.date(2026, 11, 18), today=today, post=post,
                                     now=dt.datetime(2026, 11, 17, 18))
    assert [i.title for i in items] == ["검색량 변화: 소금빵"]                 # +50%만 (베이글 +10%, 단팥빵은 거의 안 찾음)
    assert "50% 늘었다" in items[0].text and items[0].date == dt.date(2026, 11, 18)
    assert "소금빵 +50%" in notes[0]



def test_place_queries_try_address_and_names_first():
    from agent.geocode import place_queries
    q = place_queries("서울 성수동 '플레임그라운드(Flameground by BURGER KING)'")
    assert "플레임그라운드" in q and q.index("플레임그라운드") < q.index("서울 성수동 플레임그라운드")
    assert place_queries("한섬 EQL 성수, 서울 성동구 연무장15길 11")[0] == "서울 성동구 연무장15길 11"
