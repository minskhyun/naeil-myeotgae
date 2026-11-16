"""agent/events.py 테스트 (인터넷·LLM 없이): 거리·기간·공개 시각 규칙, 지어낸 근거 거르기, 취소 반영."""
import datetime as dt

import pytest

from agent import events
from agent.events import EventInfo, EventList, distance_km, page_event_signals, read_sources, seoul_event_signals

STORE = (37.5446, 127.0557)                       # 성수동 근처
D1, D2 = dt.date(2026, 11, 1), dt.date(2026, 11, 30)


def test_distance_km():
    assert distance_km(*STORE, *STORE) == 0
    assert 7.0 < distance_km(37.5665, 126.9780, 37.5446, 127.0557) < 7.5   # 서울시청 ~ 성수동 직선 약 7.3km


def _seoul(title, lat, lon, start, end, rgst="2026-11-03"):
    return dict(TITLE=title, LAT=str(lat), LOT=str(lon), STRTDATE=f"{start} 00:00:00.0", END_DATE=f"{end} 00:00:00.0",
                RGSTDATE=rgst, DATE=f"{start}~{end}", PLACE="성수 어딘가", GUNAME="성동구", ORG_LINK=f"https://x/{title}")


def test_seoul_events_rules():
    ev = [_seoul("근처하루", 37.5450, 127.0560, "2026-11-20", "2026-11-20"),
          _seoul("근처이틀", 37.5440, 127.0550, "2026-11-20", "2026-11-21", rgst="2026-11-10"),   # 같은 날 → 한 줄
          _seoul("좌표뒤바뀜", 127.0555, 37.5447, "2026-11-25", "2026-11-25"),                  # LAT·LOT 뒤바뀐 행
          _seoul("멀리", 37.5665, 126.9780, "2026-11-20", "2026-11-20"),                       # 8km → 제외
          _seoul("긴전시", 37.5450, 127.0560, "2026-11-01", "2026-12-31"),                     # 61일 → 제외
          _seoul("기간밖", 37.5450, 127.0560, "2027-01-05", "2027-01-05"),
          dict(TITLE="좌표없음", LAT="", LOT="", STRTDATE="", END_DATE="", RGSTDATE="")]
    rows, items = seoul_event_signals("s", *STORE, ev, D1, D2)
    assert [(str(r.date), r.value) for r in rows] == [("2026-11-20", 1), ("2026-11-21", 1), ("2026-11-25", 1)]
    assert rows[0].source_url == "https://x/근처하루"                       # 같은 날이면 먼저 공개된 행사
    assert rows[0].published_at == dt.datetime(2026, 11, 3, 23, 59)         # 등록일 23:59 (보수적으로)
    assert all(r.kind == "event" and r.signal == "nearby_event" for r in rows)
    assert sorted(i.title for i in items) == ["근처이틀", "근처이틀", "근처하루", "좌표뒤바뀜"]


PAGE = ("성수 팝업 소식", "11월 20일부터 21일까지 성수동 연무장길에서 ○○ 팝업스토어를 연다. 입장은 무료다.")


@pytest.fixture
def fake_llm(monkeypatch):
    calls = []

    def extractor(model, user):
        calls.append(user)
        return EventList(events=[
            EventInfo(is_event=True, title="○○ 팝업", start_date=dt.date(2026, 11, 20), end_date=dt.date(2026, 11, 21),
                      place="성수동 연무장길", cancelled=False, quote="11월 20일부터 21일까지 성수동 연무장길에서"),
            EventInfo(is_event=True, title="지어낸 행사", start_date=dt.date(2026, 11, 22), end_date=None,
                      place="성수동", cancelled=False, quote="원문에 없는 문장"),               # 근거 없음 → 버림
            EventInfo(is_event=True, title="먼 행사", start_date=dt.date(2026, 11, 23), end_date=None,
                      place="서울시청", cancelled=False, quote="입장은 무료다"),               # 8km → 버림
        ])
    monkeypatch.setitem(events.EXTRACTORS, "fake", extractor)
    monkeypatch.setattr("ml.alerts.settings", lambda: {"LLM_PROVIDER": "fake", "LLM_MODEL": "m"})
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
    def extractor(model, user):
        return EventList(events=[EventInfo(is_event=True, title="취소", start_date=dt.date(2026, 11, 20), end_date=None,
                                           place="성수동 연무장길", cancelled=True, quote="입장은 무료다")])
    monkeypatch.setitem(events.EXTRACTORS, "fake", extractor)
    monkeypatch.setattr("ml.alerts.settings", lambda: {"LLM_PROVIDER": "fake", "LLM_MODEL": "m"})
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
