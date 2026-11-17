"""한국천문연구원 특일 정보: 공휴일 수집.

공공데이터포털 '한국천문연구원_특일 정보' 활용신청이 필요하다.
"""
import datetime as dt

import requests

REST_DAY_URL = "http://apis.data.go.kr/B090041/openapi/service/SpcdeInfoService/getRestDeInfo"
SOURCE_URL = "https://www.data.go.kr/data/15012690/openapi.do"


def _months(start: dt.date, end: dt.date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def fetch_holidays(start: dt.date, end: dt.date, service_key: str):
    """start~end 사이 공휴일을 {날짜: 이름} 으로 돌려준다."""
    result = {}
    for year, month in _months(start, end):
        params = {
            "serviceKey": service_key,
            "solYear": year,
            "solMonth": f"{month:02d}",
            "numOfRows": 50,
            "_type": "json",
        }
        resp = requests.get(REST_DAY_URL, params=params, timeout=30)
        resp.raise_for_status()
        try:
            body = resp.json()["response"]["body"]
        except (ValueError, KeyError):
            raise RuntimeError(f"특일 API 응답을 읽을 수 없음: {resp.text[:300]}")

        items = body.get("items") or {}
        if not items:  # 공휴일이 없는 달은 items가 "" 로 온다
            continue
        item = items["item"]
        if isinstance(item, dict):  # 한 건이면 리스트가 아니라 dict로 온다
            item = [item]
        for it in item:
            if it.get("isHoliday") != "Y":
                continue
            s = str(it["locdate"])
            day = dt.date(int(s[:4]), int(s[4:6]), int(s[6:8]))
            if start <= day <= end:
                key = day.isoformat()
                # 같은 날 공휴일이 겹치면 이름을 이어 붙인다
                result[key] = f"{result[key]}/{it['dateName']}" if key in result else it["dateName"]
    return result