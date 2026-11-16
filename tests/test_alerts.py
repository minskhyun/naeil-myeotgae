"""alerts.py 테스트: 실제 LLM 대신 가짜 제공자로 캐시·인용 검사·자료 없음 처리를 확인한다."""
import datetime as dt

import pytest

from contracts.schemas import Forecast, ForecastRow
from ml import alerts

D = dt.date(2026, 11, 1)
FC = Forecast(store_id="s", generated_at="2026-10-31T21:00:00", signals_used=["rain_mm"],
              rows=[ForecastRow(date=D, menu="소금빵", pred=30, p10=20, p90=40, model="M2")])
ITEMS = [{"date": "2026-11-01", "title": "연세로 차 없는 거리 축제", "text": "11월 1일 연세로에서 대규모 거리 축제가 열린다.",
          "source_url": "https://news.example/1"},
         {"date": "2026-11-20", "title": "먼 행사", "text": "...", "source_url": "https://news.example/2"}]


def _warning(quote):
    return dict(date=D, menu_scope=["*"], situation_type="대형행사", direction="증가", strength="중간",
                evidence=[dict(source_url="https://news.example/1", quote=quote)], message="근처 축제로 손님이 늘 수 있어요.")


@pytest.fixture
def fake(monkeypatch):
    calls = []

    def provider(model, user):
        calls.append(user)
        return alerts.WarningList(warnings=[_warning("대규모 거리 축제가 열린다"),     # 원문에 있음
                                            _warning("10만 명이 몰린다")])           # 원문에 없음 → 버림
    monkeypatch.setitem(alerts.PROVIDERS, "fake", provider)
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    return calls


def test_warnings_keep_only_real_quotes_and_use_cache(fake, tmp_path):
    first = alerts.make_warnings(FC, ITEMS, tmp_path)
    assert [w.evidence[0].quote for w in first] == ["대규모 거리 축제가 열린다"]
    assert "먼 행사" not in fake[0]                                  # 예측 날짜 ±1일 밖의 자료는 안 넘김
    second = alerts.make_warnings(FC, ITEMS, tmp_path)
    assert second == first and len(fake) == 1                       # 같은 입력은 다시 호출하지 않음


def test_no_items_no_call(fake, tmp_path):
    assert alerts.make_warnings(FC, [ITEMS[1]], tmp_path) == [] and fake == []


def test_payload_filters_late_duplicate_and_long_items():
    """예측 시각(10/31 21:00) 뒤에 공개된 글은 빼고, 같은 글은 한 번만, 원문은 MAX_TEXT_CHARS자까지만 넘긴다."""
    base = dict(date="2026-11-01", title="축제", text="가" * (alerts.MAX_TEXT_CHARS + 50), source_url="https://a")
    items = [dict(base, published_at="2026-10-31T20:00:00+09:00"),            # 예측 전 공개 → 씀
             dict(base, published_at="2026-10-31T20:30:00"),                  # 같은 글(주소·제목) → 한 번만
             dict(base, source_url="https://late", published_at="2026-10-31T13:00:00Z"),   # UTC 13시 = KST 22시 → 늦음
             dict(base, source_url="https://no-time")]                         # 공개 시각 없음 → 씀
    p = alerts._payload(FC, items)
    assert [it["source_url"] for it in p["items"]] == ["https://a", "https://no-time"]
    assert all(len(it["text"]) == alerts.MAX_TEXT_CHARS for it in p["items"])
    late_ok = alerts._payload(FC, items, close_time="23:00")                   # 23시 마감이면 22시 글도 씀
    assert "https://late" in [it["source_url"] for it in late_ok["items"]]


def test_import_collection_validates_and_converts_time(tmp_path):
    import json
    from run import _import_collection
    src = tmp_path / "c.json"
    src.write_text(json.dumps([dict(date="2026-11-01", title="t", text="원문", source_url="u",
                                    published_at="2026-10-31T01:00:00Z")]), encoding="utf-8")
    assert _import_collection(src, tmp_path) == "원문 1개"
    saved = json.loads((tmp_path / "collection.json").read_text(encoding="utf-8"))
    assert saved[0]["published_at"] == "2026-10-31T10:00:00"                   # UTC 01시 → KST 10시
    src.write_text(json.dumps([dict(date="2026-11-01", title="t", text="", source_url="u")]), encoding="utf-8")
    with pytest.raises(SystemExit, match="0번째"):
        _import_collection(src, tmp_path)                                      # 빈 원문은 거부


def test_payload_tells_what_model_already_reflected():
    """signals_used(쓸 수 있는 신호 이름)와 별개로, 내일 실제로 반영된 근거를 신호마다 하나씩 넘긴다."""
    from contracts.schemas import Reason
    rows = [ForecastRow(date=D, menu=m, pred=30, p10=20, p90=40, model="M2",
                        reasons=[Reason(signal="rain_mm", effect_pct=e, text=f"비 {e}%")]) for m, e in [("a", -12), ("b", -20)]]
    fc = FC.model_copy(update=dict(rows=rows, signals_used=["rain_mm", "nearby_event"]))
    p = alerts._payload(fc, ITEMS)
    assert p["model_already_reflected"] == {"rain_mm": "비 -20% (예: b)"}     # nearby_event는 반영된 근거 없음


def test_menu_scope_is_cleaned(monkeypatch, tmp_path):
    """LLM이 영향 메뉴를 비우거나 없는 메뉴를 적으면 전체(["*"])로, 실제 메뉴는 그대로 둔다."""
    def provider(model, user):
        ws = [_warning("대규모 거리 축제가 열린다") for _ in range(3)]
        ws[0]["menu_scope"], ws[1]["menu_scope"], ws[2]["menu_scope"] = [], ["없는메뉴"], ["소금빵", "없는메뉴"]
        return alerts.WarningList(warnings=ws)
    monkeypatch.setitem(alerts.PROVIDERS, "fake2", provider)
    monkeypatch.setenv("LLM_PROVIDER", "fake2")
    assert [w.menu_scope for w in alerts.make_warnings(FC, ITEMS, tmp_path)] == [["*"], ["*"], ["소금빵"]]
