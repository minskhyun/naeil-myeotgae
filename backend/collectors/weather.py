"""기상청 종관기상관측(ASOS) 일자료 수집: 과거 관측 날씨.

공공데이터포털 '기상청_지상(종관, ASOS) 일자료 조회서비스' 활용신청이 필요하다.
"""
import datetime as dt

import requests

ASOS_URL = "http://apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList"
SEOUL_STATION = "108"  # 서울 관측소(종로구 송월동). 신촌에서 가장 가까운 종관 관측소
SOURCE_URL = "https://www.data.go.kr/data/15059093/openapi.do"


def _to_float(text, default=None):
    """빈 문자열은 default로 바꾼다. ASOS는 값이 없으면 ""를 준다."""
    if text is None or str(text).strip() == "":
        return default
    return float(text)


def fetch_observed(start: dt.date, end: dt.date, service_key: str, station: str = SEOUL_STATION):
    """start~end 일별 관측값을 {날짜: {...}} 로 돌려준다.

    ASOS 일자료는 어제까지만 제공되므로 end가 오늘 이후면 어제로 줄인다.
    """
    yesterday = dt.date.today() - dt.timedelta(days=1)
    end = min(end, yesterday)
    if start > end:
        return {}

    result = {}
    page = 1
    while True:
        params = {
            "serviceKey": service_key,
            "pageNo": page,
            "numOfRows": 999,
            "dataType": "JSON",
            "dataCd": "ASOS",
            "dateCd": "DAY",
            "startDt": start.strftime("%Y%m%d"),
            "endDt": end.strftime("%Y%m%d"),
            "stnIds": station,
        }
        resp = requests.get(ASOS_URL, params=params, timeout=30)
        resp.raise_for_status()
        try:
            body = resp.json()["response"]
        except (ValueError, KeyError):
            # 키 오류일 때는 JSON 대신 XML 오류 문서가 온다
            raise RuntimeError(f"기상청 API 응답을 읽을 수 없음: {resp.text[:300]}")

        code = body["header"]["resultCode"]
        if code == "03":  # NO_DATA
            break
        if code != "00":
            raise RuntimeError(f"기상청 API 오류 {code}: {body['header'].get('resultMsg')}")

        items = body["body"]["items"]["item"]
        for it in items:
            result[it["tm"]] = {
                "temp_mean": _to_float(it.get("avgTa")),
                "temp_min": _to_float(it.get("minTa")),
                "temp_max": _to_float(it.get("maxTa")),
                "rain_mm": _to_float(it.get("sumRn"), default=0.0),
            }

        total = int(body["body"]["totalCount"])
        if page * 999 >= total:
            break
        page += 1
    return result