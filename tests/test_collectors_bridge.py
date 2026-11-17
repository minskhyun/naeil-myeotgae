"""agent/collectors_bridge.py 테스트: 새얼 수집기 결과(external_daily.csv, events.json) → SignalRow·CollectionItem.
수집기 자체(인터넷·LLM)는 부르지 않고, 작은 결과 파일로 변환 규칙만 확인한다."""
import datetime as dt
import json

import pandas as pd

from agent.collectors_bridge import OBSERVED_PROXY, signals_from_collectors

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
    (tmp_path / "daily.csv").write_text(DAILY, encoding="utf-8")
    events = [_event("a", "2026-11-18", "2026-11-19", "2026-11-01T00:00:00+09:00"),
              _event("b", "2026-11-18", "2026-11-18", "2026-11-10T00:00:00+09:00"),
              _event("long", "2026-11-01", "2026-12-31", "2026-10-01T00:00:00+09:00"),    # 61일 → 제외
              _event("other", "2026-11-18", "2026-11-18", "2026-11-01T00:00:00+09:00", store="x"),   # 다른 매장
              dict(source="academic", source_url="https://univ/calendar", start_date="2026-11-16", end_date="2026-11-16")]
    (tmp_path / "events.json").write_text(json.dumps(events), encoding="utf-8")
    (tmp_path / "plans").mkdir()
    if plan:
        (tmp_path / "plans" / "s_sources.json").write_text("{}", encoding="utf-8")
    return dict(daily_path=tmp_path / "daily.csv", events_path=tmp_path / "events.json", plan_dir=tmp_path / "plans")


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
