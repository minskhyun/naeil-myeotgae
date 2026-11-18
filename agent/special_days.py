"""정해진 날짜의 기념일 → special_day 신호 (LLM 필요 없음).

카페·베이커리 판매가 흔들리는 날만 넣는다. 날짜가 매년 같으므로 '오래전에 공개된 정보'로 본다.
날을 늘리려면 SPECIAL_DAYS에 (월, 일, 이름)을 한 줄 추가한다.
"""
import datetime as dt

import pandas as pd

from contracts.schemas import SignalRow

SPECIAL_DAYS = [
    (2, 14, "발렌타인데이"),
    (3, 14, "화이트데이"),
    (11, 11, "빼빼로데이"),
    (12, 24, "크리스마스이브"),
    (12, 25, "크리스마스"),
]
SOURCE_URL = "https://ko.wikipedia.org/wiki/기념일"


def special_day_names(start, end) -> list[tuple[dt.date, str]]:
    """start~end 안의 기념일: [(날짜, 이름)] (날짜순)."""
    start, end = pd.Timestamp(start).date(), pd.Timestamp(end).date()
    found = [(dt.date(year, month, day), name) for year in range(start.year, end.year + 1) for month, day, name in SPECIAL_DAYS]
    return sorted((d, name) for d, name in found if start <= d <= end)


def special_day_signals(store_id: str, start, end) -> list[SignalRow]:
    """start~end 안의 기념일마다 special_day=1 한 줄 (kind="calendar", 공개 = 그해 1월 1일)."""
    start, end = pd.Timestamp(start).date(), pd.Timestamp(end).date()
    rows = []
    for year in range(start.year, end.year + 1):
        for month, day, _name in SPECIAL_DAYS:
            d = dt.date(year, month, day)
            if start <= d <= end:
                rows.append(SignalRow(date=d, store_id=store_id, signal="special_day", value=1.0,
                                      source_url=SOURCE_URL, published_at=dt.datetime(year - 1, 1, 1), kind="calendar"))
    return rows
