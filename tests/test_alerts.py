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
