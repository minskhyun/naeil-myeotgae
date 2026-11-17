"""agent/collect.py 테스트 (인터넷 없이): 정보원 목록을 차례로 실행하고, 하나가 실패해도 나머지는 계속한다."""
import datetime as dt

from agent import collect
from contracts.schemas import CollectionItem, SignalRow, StoreConfig

STORE = StoreConfig(store_id="s", address="서울 성동구 서울숲2길 12-7", lat=37.5, lon=127.0)
D1, D2 = dt.date(2026, 11, 1), dt.date(2026, 11, 30)


def _row(job):
    return SignalRow(date=job.start, store_id=job.store.store_id, signal="special_day", value=1.0, source_url="u",
                     published_at=dt.datetime(2026, 1, 1), kind="calendar")


def test_collect_all_merges_sources_and_survives_failures(monkeypatch, tmp_path):
    def good(job):
        return [_row(job)], [CollectionItem(date=job.start, title="t", text="원문", source_url="u")], ["좋음"]

    def broken(job):
        raise RuntimeError("API가 응답하지 않음")

    monkeypatch.setattr(collect, "SOURCES", [("고장난 정보원", broken), ("정상", good), ("정상2", good)])
    rows, items, notes = collect.collect_all(STORE, D1, D2, tmp_path, menus=["소금빵"])
    assert len(rows) == 2 and len(items) == 2                                   # 정상인 정보원 두 개의 결과가 합쳐짐
    assert notes == ["고장난 정보원 실패(RuntimeError) → 이 정보 없이 진행", "좋음", "좋음"]


def test_menu_trend_is_skipped_without_target_or_menus(tmp_path):
    job = collect.CollectJob(STORE, D1, D2, tmp_path)                           # 예측 날짜·메뉴가 없으면 부르지 않음
    assert collect.menu_trend(job) == ([], [], [])


def test_special_days_source(tmp_path):
    job = collect.CollectJob(STORE, D1, D2, tmp_path)
    rows, items, notes = collect.special_days(job)
    assert [(str(r.date), r.signal) for r in rows] == [("2026-11-11", "special_day")] and not items   # 빼빼로데이


def test_report_summarizes_what_was_collected(tmp_path):
    """sources_report.json: 신호는 이름별로 며칠치·기간·출처, 글은 여러 날에 걸쳐도 한 줄, 관측값 대용은 밝힌다."""
    import json

    import pandas as pd

    from agent.collectors_bridge import OBSERVED_PROXY
    from agent.report import build_report
    rows = [dict(date=f"2026-11-{d:02d}", store_id="s", signal="temp_mean", menu=None, value=10.0,
                 source_url="https://data.kma.go.kr" + OBSERVED_PROXY, published_at="2026-11-01T17:10:00", kind="forecast")
            for d in (10, 11, 12)]
    rows += [dict(date="2026-11-12", store_id="s", signal="trend_level", menu=m, value=1.2,
                  source_url="https://datalab.naver.com", published_at="2026-11-11T09:00:00", kind="observed")
             for m in ("소금빵", "베이글")]
    pd.DataFrame(rows).to_csv(tmp_path / "signals.csv", index=False, encoding="utf-8")
    items = [dict(date=f"2026-11-{d}", title="성수 팝업", text="원문", source_url="https://blog/1") for d in (13, 14, 15)]
    (tmp_path / "collection.json").write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")

    report = build_report("s", tmp_path, ["날씨 3일"])
    by_signal = {x.signal: x for x in report.signals}
    assert (by_signal["temp_mean"].n_days, by_signal["temp_mean"].source_url) == (3, "https://data.kma.go.kr")
    assert "관측값" in by_signal["temp_mean"].note and by_signal["trend_level"].note is None
    assert (by_signal["trend_level"].n_days, by_signal["trend_level"].n_menus) == (1, 2)
    assert [(a.title, str(a.first_date), str(a.last_date)) for a in report.articles] == [("성수 팝업", "2026-11-13", "2026-11-15")]
    assert report.plan is None and report.n_nearby is None and report.notes == ["날씨 3일"]   # 정보원 계획이 없는 매장
