"""agent/special_days.py·build.py 테스트 (인터넷 없이)."""
import datetime as dt

from agent.build import merge_weather
from agent.special_days import special_day_signals
from contracts.schemas import SignalRow


def test_special_days_in_range():
    rows = special_day_signals("s", "2026-11-01", "2026-12-24")
    assert [str(r.date) for r in rows] == ["2026-11-11", "2026-12-24"]
    assert all(r.kind == "calendar" and r.value == 1 and r.published_at < dt.datetime(2026, 1, 1) for r in rows)


def test_live_forecast_replaces_proxy_on_same_date():
    def row(day, url):
        return SignalRow(date=day, store_id="s", signal="rain_mm", value=1, source_url=url,
                         published_at="2026-11-16T17:10:00", kind="forecast")
    proxy = [row("2026-11-16", "proxy"), row("2026-11-17", "proxy")]
    live = [row("2026-11-17", "live"), row("2026-11-18", "live")]
    assert [(str(r.date), r.source_url) for r in merge_weather(proxy, live)] == [
        ("2026-11-16", "proxy"), ("2026-11-17", "live"), ("2026-11-18", "live")]
