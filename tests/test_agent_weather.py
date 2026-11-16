"""agent/weather.py 테스트 (인터넷 없이): 격자 변환, 강수량 표기, 하루 값 묶기."""
from agent.weather import daily_from_items, latlon_to_grid, parse_pcp


def test_latlon_to_grid_matches_kma_table():
    assert latlon_to_grid(37.5665, 126.9780) == (60, 127)       # 서울시청 (기상청 격자표)


def test_parse_pcp():
    assert [parse_pcp(v) for v in ["강수없음", "1mm 미만", "3.0mm", "30.0~50.0mm", "50.0mm 이상"]] == [0, 0.5, 3, 40, 50]


def test_daily_from_items_needs_full_day():
    def item(day, hour, cat, v):
        return dict(fcstDate=day, fcstTime=f"{hour:02d}00", category=cat, fcstValue=v)
    full = [item("20261117", h, "TMP", str(h)) for h in range(24)] + [item("20261117", 9, "PCP", "2.0mm"),
                                                                      item("20261117", 10, "PCP", "1mm 미만")]
    part = [item("20261116", h, "TMP", "10") for h in range(18, 24)]          # 발표 당일 저녁만 → 뺀다
    d = daily_from_items(full + part)
    assert d["date"].dt.strftime("%Y-%m-%d").tolist() == ["2026-11-17"]
    assert d.loc[0, "temp_mean"] == 11.5 and d.loc[0, "rain_mm"] == 2.5          # (0+…+23)/24, 2.0+0.5
