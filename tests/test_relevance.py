"""agent/relevance.py 테스트 (LLM 없이): 근처 행사를 규모·거리·가게(메뉴)와의 연관도로 따져 메뉴별 신호 event_impact로."""
import datetime as dt

import pytest

from agent import relevance
from agent.relevance import MenuScore, Rating, RatingList, event_impact, event_key, event_weight, impact_rows
from contracts.schemas import StoreConfig
from ml import llm

STORE = StoreConfig(store_id="s", name="우리 빵집", address="서울 성동구 서울숲2길 12-7", lat=37.5, lon=127.0)
MENUS = ["아이스 아메리카노", "소금빵"]
D1, D2 = dt.date(2026, 11, 1), dt.date(2026, 11, 30)


def _event(title, start, end, distance_km, published, cancelled=False):
    return dict(title=title, place="서울숲", category="축제", start=dt.date(2026, 11, start), end=dt.date(2026, 11, end),
                distance_km=distance_km, published_at=dt.datetime(2026, 10, published, 23, 59), url=f"https://x/{title}",
                cancelled=cancelled, snippet=None)


FESTIVAL = _event("서울숲 가을 축제", 7, 8, 0.2, published=20)      # 크고 가깝고 관련 깊음
TALK = _event("도서관 북토크", 7, 7, 0.9, published=25)             # 작고 멀고 관련 적음


@pytest.fixture
def fake_llm(monkeypatch):
    """가짜 LLM: 축제는 규모 5·연관도 4(아이스 음료는 5), 북토크는 규모 1·연관도 1. 없는 메뉴 이름과 범위 밖 점수도 섞어 준다."""
    calls = []

    def provider(user, **_):
        import json
        events = json.loads(user)["events"]
        calls.append([e["title"] for e in events])
        out = []
        for e in events:
            if "축제" in e["title"]:
                out.append(Rating(id=e["id"], scale=9, relevance=4, reason="야외 축제",       # 9 → 5로 깎임
                                  menus=[MenuScore(menu="아이스 아메리카노", score=5), MenuScore(menu="없는 메뉴", score=5)]))
            else:
                out.append(Rating(id=e["id"], scale=1, relevance=1, reason="소모임", menus=[]))
        return RatingList(ratings=out)
    monkeypatch.setitem(llm.PROVIDERS, "fake", provider)
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    return calls


def test_weight_combines_scale_relevance_and_distance():
    assert event_weight(5, 5, 0.0) == 1.0                                   # 가장 크고, 가장 관련 있고, 바로 앞
    assert event_weight(5, 5, 0.5) == 0.5                                   # 500m 떨어지면 절반
    assert event_weight(1, 5, 0.0) == pytest.approx(0.2)                    # 작은 행사
    assert event_weight(5, 1, 0.0) == pytest.approx(0.2)                    # 우리 가게와 무관한 행사
    assert event_weight(5, 5, 3.0) == pytest.approx(relevance.MIN_CLOSENESS)   # 멀어도 0은 아니다


def test_event_impact_is_per_menu_and_cached(fake_llm, tmp_path):
    rows, notes = event_impact(STORE, MENUS, [FESTIVAL, TALK], D1, D2, tmp_path)
    value = {(str(r.date), r.menu): r.value for r in rows if r.published_at.day == 25}     # 두 행사가 모두 공개된 뒤의 값
    talk = event_weight(1, 1, 0.9)
    # 11/7: 축제 + 북토크. 아이스 음료는 축제와의 연관도가 5, 소금빵은 가게 전체 점수 4
    assert value[("2026-11-07", "아이스 아메리카노")] == pytest.approx(event_weight(5, 5, 0.2) + talk, abs=1e-4)
    assert value[("2026-11-07", "소금빵")] == pytest.approx(event_weight(5, 4, 0.2) + talk, abs=1e-4)
    assert {r.signal for r in rows} == {"event_impact"} and {r.kind for r in rows} == {"event"}
    assert notes[0] == "행사 평가 2건 (새로 물은 것 2건)"

    again, notes = event_impact(STORE, MENUS, [FESTIVAL, TALK], D1, D2, tmp_path)           # 같은 행사는 다시 묻지 않는다
    assert len(fake_llm) == 1 and notes[0] == "행사 평가 2건 (새로 물은 것 0건)" and len(again) == len(rows)
    new = _event("성수 팝업", 20, 21, 0.3, published=28)
    event_impact(STORE, MENUS, [FESTIVAL, TALK, new], D1, D2, tmp_path)                    # 새 행사만 묻는다
    assert fake_llm[-1] == ["성수 팝업"]


def test_impact_grows_as_events_are_published_and_cancel_resets():
    """시점 규칙: 행사가 공개될 때마다 그날의 합이 늘어난다. 취소 공지가 공개되면 0."""
    ratings = {event_key(FESTIVAL): dict(scale=5, relevance=5, menus={}), event_key(TALK): dict(scale=5, relevance=5, menus={})}
    cancel = _event("서울숲 가을 축제 취소", 7, 7, 0.2, published=30, cancelled=True)
    rows = impact_rows("s", [TALK, FESTIVAL, cancel], ratings, ["소금빵"], D1, D2)
    day7 = [(r.published_at.day, r.value) for r in rows if str(r.date) == "2026-11-07"]
    assert day7 == [(20, pytest.approx(0.8)), (25, pytest.approx(0.9)), (30, 0.0)]          # 축제 → +북토크 → 취소
    assert [(r.published_at.day, r.value) for r in rows if str(r.date) == "2026-11-08"] == [(20, pytest.approx(0.8))]

    same_time = _event("같은 날 등록된 행사", 7, 7, 0.0, published=20)                       # 공개 시각이 같으면 합친 뒤 한 줄만
    rows = impact_rows("s", [FESTIVAL, same_time], ratings, ["소금빵"], D1, D2)
    assert len([r for r in rows if str(r.date) == "2026-11-07"]) == 1


def test_no_events_or_llm_failure(monkeypatch, tmp_path):
    assert event_impact(STORE, MENUS, [], D1, D2, tmp_path) == ([], [])                    # 행사가 없으면 LLM도 안 부른다
    assert event_impact(STORE, [], [FESTIVAL], D1, D2, tmp_path) == ([], [])

    def broken(**_):
        raise TimeoutError
    monkeypatch.setitem(llm.PROVIDERS, "fake", broken)
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    rows, notes = event_impact(STORE, MENUS, [FESTIVAL], D1, D2, tmp_path)                  # LLM이 안 되면 보통 점수(3)로 계산
    assert rows[0].value == pytest.approx(event_weight(3, 3, 0.2), abs=1e-4) and "보통 점수" in notes[1]


# ---------------------------------------------------------------- 기념일

def test_special_impact_differs_by_day_and_menu(monkeypatch, tmp_path):
    """기념일마다, 메뉴마다 다르다: 빼빼로데이는 과자류에 크고 커피에는 작다. 다가올수록 커진다."""
    from agent.relevance import SpecialRating, SpecialRatingList, special_impact
    asked = []

    def provider(user, **_):
        import json
        names = json.loads(user)["special_days"]
        asked.append(names)
        return SpecialRatingList(ratings=[SpecialRating(name=n, relevance=2, reason="선물용 과자를 사는 날",
                                                        menus=[MenuScore(menu="휘낭시에", score=5)]) for n in names])
    monkeypatch.setitem(llm.PROVIDERS, "fake", provider)
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    rows, notes = special_impact(STORE, ["휘낭시에", "아메리카노"], D1, D2, tmp_path)       # 11월: 빼빼로데이(11/11)
    value = {(str(r.date), r.menu): r.value for r in rows}
    assert value[("2026-11-11", "휘낭시에")] == 1.0 and value[("2026-11-11", "아메리카노")] == 0.4      # 당일: 5/5, 2/5
    assert value[("2026-11-10", "휘낭시에")] == pytest.approx(7 / 8) and value[("2026-11-04", "휘낭시에")] == pytest.approx(1 / 8)
    assert ("2026-11-03", "휘낭시에") not in value and ("2026-11-12", "휘낭시에") not in value            # 일주일 전부터 당일까지만
    assert {r.signal for r in rows} == {"special_impact"} and all(r.published_at.year == 2025 for r in rows)
    assert asked == [["빼빼로데이"]] and notes == ["기념일 평가 1개 (새로 물은 것 1개)"]

    special_impact(STORE, ["휘낭시에", "아메리카노"], D1, D2, tmp_path)                    # 같은 기념일은 다시 묻지 않는다
    assert len(asked) == 1
    assert special_impact(STORE, [], D1, D2, tmp_path) == ([], [])                         # 메뉴가 없으면 LLM도 안 부른다
    assert special_impact(STORE, ["휘낭시에"], dt.date(2026, 6, 1), dt.date(2026, 6, 30), tmp_path) == ([], [])   # 기념일이 없는 달
