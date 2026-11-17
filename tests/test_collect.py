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
