"""정해진 날짜의 기념일 → special_day(당일)·special_lead(앞둔 날) 신호 (LLM 필요 없음).

카페·베이커리 판매가 흔들리는 날만 넣는다. 날짜가 매년 같으므로 '오래전에 공개된 정보'로 본다.
날을 늘리려면 SPECIAL_DAYS에 (월, 일, 이름)을 한 줄 추가한다.
"""
import datetime as dt

import pandas as pd

from contracts.schemas import SignalRow
from ml.features import SPECIAL_LEAD_DAYS

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
    """start~end의 날짜마다 (kind="calendar", 달력은 미리 알려진 것이므로 공개 = 그 전해 1월 1일)
        special_day  = 1        기념일 당일
        special_lead = 7 … 1    기념일을 앞둔 날 (전날 7, 일주일 전 1). 수요는 당일만이 아니라 며칠 전부터 움직인다
    기념일이 가까이 없는 날은 줄을 만들지 않는다 (예측 엔진이 0으로 채움)."""
    start, end = pd.Timestamp(start).date(), pd.Timestamp(end).date()
    ahead = end + dt.timedelta(days=SPECIAL_LEAD_DAYS)          # end 바로 뒤의 기념일도 end 전 며칠에 영향을 준다
    days = {d for d, _name in special_day_names(start, ahead)}

    def row(day: dt.date, signal: str, value: float, special: dt.date) -> SignalRow:
        return SignalRow(date=day, store_id=store_id, signal=signal, value=value, source_url=SOURCE_URL,
                         published_at=dt.datetime(special.year - 1, 1, 1), kind="calendar")

    rows = []
    for stamp in pd.date_range(start, end):
        day = stamp.date()
        if day in days:
            rows.append(row(day, "special_day", 1.0, day))
            continue
        left = next((n for n in range(1, SPECIAL_LEAD_DAYS + 1) if day + dt.timedelta(days=n) in days), None)
        if left is not None:                                    # left일 뒤가 기념일 → 가까울수록 큰 값
            rows.append(row(day, "special_lead", float(SPECIAL_LEAD_DAYS + 1 - left), day + dt.timedelta(days=left)))
    return rows
