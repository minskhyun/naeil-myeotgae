"""agent/events.py 테스트 (인터넷·LLM 없이): 거리·기간·공개 시각 규칙, 지어낸 근거 거르기, 취소 반영."""
import datetime as dt

import pytest

from agent import events
from agent.events import EventInfo, EventList, distance_km, page_event_signals, read_sources
from ml import llm

STORE = (37.5446, 127.0557)                       # 성수동 근처
D1, D2 = dt.date(2026, 11, 1), dt.date(2026, 11, 30)


def test_distance_km():
    assert distance_km(*STORE, *STORE) == 0
    assert 7.0 < distance_km(37.5665, 126.9780, 37.5446, 127.0557) < 7.5   # 서울시청 ~ 성수동 직선 약 7.3km


PAGE = ("성수 팝업 소식", "11월 20일부터 21일까지 성수동 연무장길에서 ○○ 팝업스토어를 연다. 입장은 무료다.")


@pytest.fixture
def fake_llm(monkeypatch):
    calls = []

    def extractor(user, **_):
        calls.append(user)
        return EventList(events=[
            EventInfo(is_event=True, title="○○ 팝업", start_date=dt.date(2026, 11, 20), end_date=dt.date(2026, 11, 21),
                      place="성수동 연무장길", cancelled=False, quote="11월 20일부터 21일까지 성수동 연무장길에서"),
            EventInfo(is_event=True, title="지어낸 행사", start_date=dt.date(2026, 11, 22), end_date=None,
                      place="성수동", cancelled=False, quote="원문에 없는 문장"),               # 근거 없음 → 버림
            EventInfo(is_event=True, title="먼 행사", start_date=dt.date(2026, 11, 23), end_date=None,
                      place="서울시청", cancelled=False, quote="입장은 무료다"),               # 8km → 버림
        ])
    monkeypatch.setitem(llm.PROVIDERS, "fake", extractor)
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    return calls


def _geocode(place):
    return (37.5665, 126.9780, "시청") if place == "서울시청" else (37.5440, 127.0570, "연무장길")


def test_page_events_keep_only_grounded_near(fake_llm, tmp_path):
    rows, items, notes = page_event_signals("s", *STORE, [("https://blog/1", dt.datetime(2026, 11, 5, 10))], D1, D2,
                                            tmp_path, fetch=lambda u: PAGE, geocode=_geocode)
    assert [(str(r.date), r.value) for r in rows] == [("2026-11-20", 1), ("2026-11-21", 1)]
    assert rows[0].published_at == dt.datetime(2026, 11, 5, 10) and len(items) == 2
    page_event_signals("s", *STORE, [("https://blog/1", dt.datetime(2026, 11, 5, 10))], D1, D2,
                       tmp_path, fetch=lambda u: PAGE, geocode=_geocode)
    assert len(fake_llm) == 1                                              # 같은 글은 캐시 (다시 안 부름)


def test_cancelled_event_is_zero_and_unknown_time_is_now(monkeypatch, tmp_path):
    def extractor(user, **_):
        return EventList(events=[EventInfo(is_event=True, title="취소", start_date=dt.date(2026, 11, 20), end_date=None,
                                           place="성수동 연무장길", cancelled=True, quote="입장은 무료다")])
    monkeypatch.setitem(llm.PROVIDERS, "fake", extractor)
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    now = dt.datetime(2026, 11, 16, 12)
    rows, _, _ = page_event_signals("s", *STORE, [("https://n/2", None)], D1, D2, tmp_path,
                                    fetch=lambda u: PAGE, geocode=_geocode, now=now)
    assert [(str(r.date), r.value, r.published_at) for r in rows] == [("2026-11-20", 0, now)]


def test_page_fetch_failure_is_noted(fake_llm, tmp_path):
    def broken(url):
        raise TimeoutError
    rows, items, notes = page_event_signals("s", *STORE, [("https://down", None)], D1, D2, tmp_path,
                                            fetch=broken, geocode=_geocode)
    assert rows == [] and "못 받음" in notes[0]


def test_read_sources(tmp_path):
    p = tmp_path / "s.txt"
    p.write_text("# 성수 팝업\nhttps://a 2026-11-05\n\nhttps://b\n", encoding="utf-8")
    assert read_sources(p) == [("https://a", dt.datetime(2026, 11, 5)), ("https://b", None)]


def test_geocode_saves_hits_and_misses(tmp_path, monkeypatch):
    """찾은 주소·못 찾은 주소 모두 파일에 저장 → 두 번째는 지도 서비스를 다시 부르지 않는다. 번지부터 줄여 가며 찾는다."""
    from agent import geocode as g
    monkeypatch.setattr(g, "CACHE_PATH", tmp_path / "cache.json")
    monkeypatch.setattr(g, "_cache", None)
    calls = []

    def search(q):
        calls.append(q)
        return {"lat": "37.5", "lon": "127.0", "display_name": "성수이로"} if q == "서울 성동구 성수이로" else None
    assert g.geocode("서울 성동구 성수이로 75 도레미약국", search=search)[:2] == (37.5, 127.0)
    assert calls == ["서울 성동구 성수이로 75 도레미약국", "서울 성동구 성수이로 75", "서울 성동구 성수이로"]
    with pytest.raises(ValueError):
        g.geocode("없는 곳", search=lambda q: None)
    monkeypatch.setattr(g, "_cache", None)                                  # 프로그램을 새로 켠 것처럼
    assert g.geocode("서울 성동구 성수이로 75 도레미약국", search=search)[:2] == (37.5, 127.0) and len(calls) == 3
    with pytest.raises(ValueError, match="저장된 결과"):
        g.geocode("없는 곳", search=search)
