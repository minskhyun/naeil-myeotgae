"""agent/collectors_bridge.py 테스트: 수집기 결과(external_daily.csv, events.json) → SignalRow·CollectionItem.
수집기 자체(인터넷·LLM)는 부르지 않고, 작은 결과 파일로 변환 규칙만 확인한다."""
import datetime as dt
import json

import pandas as pd

from agent.collectors_bridge import OBSERVED_PROXY, ensure_store, signals_from_collectors
from contracts.schemas import StoreConfig

DAILY = """date,dow,is_weekend,is_holiday,holiday_name,temp_mean,temp_min,temp_max,rain_mm,weather_kind,weather_issued_at,exam_period,vacation,festival,nearby_event
2026-11-16,0,0,0,,9.1,5.0,13.0,0.0,observed,,1,0,0,0
2026-11-17,1,0,0,,,,,,,,0,0,0,0
2026-11-18,2,0,0,,6.2,5.0,9.0,2.5,forecast,2026-11-17T05:00:00+09:00,0,0,0,0
"""


def _event(eid, start, end, reg, store="s", source="seoul_culture"):
    return dict(event_id=eid, source=source, store_id=store, type="event", category="공연", title=f"행사{eid}",
                place="서울숲", distance_m=300, start_date=start, end_date=end,
                source_url=f"https://culture/{eid}", published_at=reg, verified=True)


def _files(tmp_path, plan=True):
    (tmp_path / "external_daily.csv").write_text(DAILY, encoding="utf-8")
    events = [_event("a", "2026-11-18", "2026-11-19", "2026-11-01T00:00:00+09:00"),
              _event("b", "2026-11-18", "2026-11-18", "2026-11-10T00:00:00+09:00"),
              _event("long", "2026-11-01", "2026-12-31", "2026-10-01T00:00:00+09:00"),    # 61일 → 제외
              _event("other", "2026-11-18", "2026-11-18", "2026-11-01T00:00:00+09:00", store="x"),   # 다른 매장
              dict(source="academic", source_url="https://univ/calendar", start_date="2026-11-16", end_date="2026-11-16")]
    (tmp_path / "events.json").write_text(json.dumps(events), encoding="utf-8")
    if plan:
        (tmp_path / "s_sources.json").write_text("{}", encoding="utf-8")
    return dict(work_dir=tmp_path)                                         # 수집기가 매장별 폴더에 남기는 모양 그대로


def test_weather_publish_times(tmp_path):
    rows, _, _ = signals_from_collectors("s", dt.date(2026, 11, 1), dt.date(2026, 11, 30), **_files(tmp_path))
    w = {(str(r.date), r.signal): r for r in rows if r.signal in ("temp_mean", "rain_mm")}
    obs = w[("2026-11-16", "temp_mean")]                                    # 관측값 → 전날 17:10 예보처럼, 표시
    assert obs.published_at == dt.datetime(2026, 11, 15, 17, 10) and obs.source_url.endswith(OBSERVED_PROXY)
    fc = w[("2026-11-18", "rain_mm")]                                       # 예보 → 발표 시각 (한국 시간)
    assert fc.value == 2.5 and fc.published_at == dt.datetime(2026, 11, 17, 5, 0) and OBSERVED_PROXY not in fc.source_url
    assert ("2026-11-17", "temp_mean") not in w                             # 값 없는 날은 줄 없음


def test_academic_needs_plan(tmp_path):
    rows, _, notes = signals_from_collectors("s", dt.date(2026, 11, 1), dt.date(2026, 11, 30), **_files(tmp_path))
    ac = [r for r in rows if r.signal == "exam_period"]
    assert [(str(r.date), r.value, r.published_at) for r in ac] == [("2026-11-16", 1.0, dt.datetime(2026, 1, 1))]
    no_plan = tmp_path / "noplan"                                           # 정보원 계획이 없는 매장
    no_plan.mkdir()
    rows, _, notes = signals_from_collectors("s", dt.date(2026, 11, 1), dt.date(2026, 11, 30),
                                             **_files(no_plan, plan=False))
    assert not [r for r in rows if r.signal == "exam_period"] and any("학사일정 안 씀" in n for n in notes)


def test_event_counts_grow_as_events_are_registered(tmp_path):
    rows, items, _ = signals_from_collectors("s", dt.date(2026, 11, 1), dt.date(2026, 11, 30), **_files(tmp_path))
    ev = [(str(r.date), r.value, r.published_at) for r in rows if r.signal == "nearby_event"]
    assert ev == [("2026-11-18", 1.0, dt.datetime(2026, 11, 1, 23, 59)),     # a 등록 → 1개
                  ("2026-11-18", 2.0, dt.datetime(2026, 11, 10, 23, 59)),    # b 등록 → 2개
                  ("2026-11-19", 1.0, dt.datetime(2026, 11, 1, 23, 59))]
    assert sorted({i.title for i in items}) == ["행사a", "행사b"]            # 긴 행사·다른 매장 제외
    assert all(pd.Timestamp(i.date) >= pd.Timestamp("2026-11-18") for i in items)


def test_store_file_is_per_store_and_replans_when_address_changes(tmp_path):
    work = tmp_path / "collectors"
    here = StoreConfig(store_id="s", address="서울 성동구 서울숲2길 12-7", lat=37.5, lon=127.0)
    ensure_store(here, work)
    assert [s["store_id"] for s in json.loads((work / "stores.json").read_text(encoding="utf-8"))] == ["s"]
    (work / "s_sources.json").write_text("{}", encoding="utf-8")
    ensure_store(here, work)
    assert (work / "s_sources.json").exists()                               # 같은 주소 → 계획 그대로
    ensure_store(StoreConfig(store_id="s", address="서울 서대문구 연세로 50", lat=37.56, lon=126.94), work)
    assert not (work / "s_sources.json").exists()                           # 주소가 바뀜 → 다시 고르게 지움


def test_hide_keys_in_logs():
    from agent.collectors_bridge import hide_keys
    line = "403 Forbidden for url: http://apis.data.go.kr/x?serviceKey=abc123SECRET&solYear=2026 KEY=zz"
    assert "abc123SECRET" not in hide_keys(line) and "serviceKey=***&solYear=2026" in hide_keys(line)


def test_tell_coverage_says_the_whole_period():
    """화면 알림: 날씨·학교 일정을 하루치가 아니라 기간 전체로 가져왔다는 것 (언제부터 언제까지, 시험·방학이 몇 번)."""
    from agent import collectors_bridge as bridge
    from ml import progress
    day = lambda m, d: dt.date(2026, m, d)                                     # noqa: E731
    exams = {day(4, d) for d in range(20, 26)} | {day(6, d) for d in range(15, 21)}        # 중간·기말 = 2번
    assert bridge.periods(exams) == 2 and bridge.periods([]) == 0
    progress.reset()
    bridge.tell_coverage({"temp_mean": {day(1, 1), day(6, 30)}, "exam_period": exams, "vacation": {day(6, 22), day(6, 23)}})
    weather, school = progress.EVENTS
    assert weather == dict(kind="weather", days=2, first=day(1, 1), last=day(6, 30))
    assert school == dict(kind="academic", days=14, first=day(4, 20), last=day(6, 23), exams=2, vacations=1, festivals=0)
    progress.reset()
    bridge.tell_coverage({})                                                   # 가져온 것이 없으면 알리지 않는다
    assert progress.EVENTS == []
