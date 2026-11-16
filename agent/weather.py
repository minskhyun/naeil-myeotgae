"""기상청 단기예보 → 날씨 신호(SignalRow: temp_mean, rain_mm, kind="forecast").

    python -m agent.weather --store seongsu-a --lat 37.5446 --lon 127.0557      # 오늘 17시 발표본 → 내일·모레

- 출처: 공공데이터포털 '기상청_단기예보 조회서비스'. 키는 .env의 DATA_GO_KR_KEY (일반 인증키, 디코딩).
- ★ API는 최근 3일 발표본만 준다. 학습용 과거 예보(한 달 전)는 이 모듈로 받을 수 없다
  → docs/LLM_AGENT_CONTEXT.md 11절 '결정 필요' 1번.
- 하루 한 번 17시 발표본을 쓴다 (발표 10분 뒤 공개로 본다). 21시 영업 종료 전에 공개되므로 다음 날 예측에 쓰인다.
- 하루 값으로 묶는 방법 (모든 기간 같은 규칙):
    temp_mean = 그날 0~23시 시간별 예보 기온(TMP) 평균  (24시간이 다 있는 날만)
    rain_mm   = 그날 시간별 예보 강수량(PCP) 합
"""
import argparse
import datetime as dt
import json
import math
import sys
import urllib.parse
import urllib.request

import pandas as pd

from contracts.schemas import SignalRow

URL = "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"   # https는 응답이 없어 http
SOURCE_URL = "https://www.data.go.kr/data/15084084/openapi.do"                    # 화면 근거 링크 (단기예보 조회서비스)
BASE_TIME = "1700"
PUBLISH_DELAY = pd.Timedelta(minutes=10)      # 발표 시각 + 10분에 공개된다고 본다


def latlon_to_grid(lat: float, lon: float) -> tuple[int, int]:
    """위도·경도 → 기상청 예보 격자 (nx, ny). 기상청이 공개한 람베르트 정각원추도법 변환식."""
    RE, GRID, SLAT1, SLAT2, OLON, OLAT, XO, YO = 6371.00877, 5.0, 30.0, 60.0, 126.0, 38.0, 43, 136
    d = math.pi / 180.0
    re = RE / GRID
    slat1, slat2, olon, olat = SLAT1 * d, SLAT2 * d, OLON * d, OLAT * d
    sn = math.log(math.cos(slat1) / math.cos(slat2)) / math.log(
        math.tan(math.pi / 4 + slat2 / 2) / math.tan(math.pi / 4 + slat1 / 2))
    sf = math.tan(math.pi / 4 + slat1 / 2) ** sn * math.cos(slat1) / sn
    ro = re * sf / math.tan(math.pi / 4 + olat / 2) ** sn
    ra = re * sf / math.tan(math.pi / 4 + lat * d / 2) ** sn
    theta = (lon * d - olon + math.pi) % (2 * math.pi) - math.pi
    theta *= sn
    return int(ra * math.sin(theta) + XO + 0.5), int(ro - ra * math.cos(theta) + YO + 0.5)


def parse_pcp(v: str) -> float:
    """강수량 표기 → mm.  '강수없음'→0, '1mm 미만'→0.5, '3.0mm'→3, '30.0~50.0mm'→40(가운데), '50.0mm 이상'→50."""
    v = str(v).strip()
    if v in ("강수없음", "", "0", "-"):
        return 0.0
    if "미만" in v:
        return 0.5
    nums = [float(x) for x in pd.Series([v]).str.findall(r"\d+(?:\.\d+)?")[0]]
    return sum(nums) / len(nums) if nums else 0.0


def daily_from_items(items: list[dict]) -> pd.DataFrame:
    """API 항목들 → 날짜별 [date, temp_mean, rain_mm]. 시간별 기온이 24개 다 있는 날만 (발표 당일 저녁 등 일부만 있는 날은 뺀다)."""
    df = pd.DataFrame(items)
    if df.empty:
        return pd.DataFrame(columns=["date", "temp_mean", "rain_mm"])
    df["date"] = pd.to_datetime(df["fcstDate"], format="%Y%m%d")
    tmp = df[df["category"] == "TMP"].assign(v=lambda x: x["fcstValue"].astype(float))
    pcp = df[df["category"] == "PCP"].assign(v=lambda x: x["fcstValue"].map(parse_pcp))
    t = tmp.groupby("date")["v"].agg(["mean", "count"])
    out = pd.DataFrame({"temp_mean": t["mean"].round(1), "rain_mm": pcp.groupby("date")["v"].sum().round(1)})
    out = out[t["count"] == 24].reset_index()
    return out[["date", "temp_mean", "rain_mm"]]


def fetch_items(key: str, base_date: str, nx: int, ny: int, base_time: str = BASE_TIME) -> list[dict]:
    """한 발표본의 모든 항목 (여러 쪽이면 이어서 받는다)."""
    items, page = [], 1
    while True:
        q = dict(serviceKey=key, pageNo=page, numOfRows=1000, dataType="JSON",
                 base_date=base_date, base_time=base_time, nx=nx, ny=ny)
        with urllib.request.urlopen(f"{URL}?{urllib.parse.urlencode(q)}", timeout=30) as r:
            body = r.read().decode("utf-8")
        try:
            res = json.loads(body)["response"]
        except (json.JSONDecodeError, KeyError):
            raise RuntimeError(f"기상청 응답이 JSON이 아닙니다 (키가 틀렸거나 아직 활성화 전일 수 있음): {body[:200]}")
        head = res["header"]
        if head["resultCode"] != "00":
            raise RuntimeError(f"기상청 API 오류 {head['resultCode']}: {head['resultMsg']} (base_date={base_date})")
        b = res["body"]
        items += b["items"]["item"]
        if len(items) >= int(b["totalCount"]):
            return items
        page += 1


def forecast_signals(store_id: str, lat: float, lon: float, base_date: str, key: str) -> list[SignalRow]:
    """base_date 17시 발표본 → 그 뒤 날짜들의 SignalRow (temp_mean, rain_mm). published_at = 발표 시각 + 10분 (KST)."""
    nx, ny = latlon_to_grid(lat, lon)
    published = pd.Timestamp(f"{base_date} {BASE_TIME[:2]}:{BASE_TIME[2:]}") + PUBLISH_DELAY
    rows = []
    for d in daily_from_items(fetch_items(key, base_date, nx, ny)).itertuples():
        for signal, value in (("temp_mean", d.temp_mean), ("rain_mm", d.rain_mm)):
            rows.append(SignalRow(date=d.date.date(), store_id=store_id, signal=signal, value=float(value),
                                  source_url=SOURCE_URL, published_at=published.to_pydatetime(), kind="forecast"))
    return rows


def main(argv=None):
    from ml.alerts import settings                      # .env 읽기를 한곳에서 (DATA_GO_KR_KEY)
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="기상청 단기예보 → 날씨 신호(JSON, SignalRow 목록)")
    p.add_argument("--store", required=True)
    p.add_argument("--lat", type=float, required=True)
    p.add_argument("--lon", type=float, required=True)
    p.add_argument("--base-date", default=dt.date.today().strftime("%Y%m%d"), help="발표일 YYYYMMDD (최근 3일만 가능)")
    p.add_argument("--out", help="저장할 .json (없으면 화면에만)")
    a = p.parse_args(argv)
    key = settings().get("DATA_GO_KR_KEY")
    if not key:
        raise SystemExit(".env에 DATA_GO_KR_KEY가 없습니다.")
    rows = forecast_signals(a.store, a.lat, a.lon, a.base_date, key)
    data = [r.model_dump(mode="json") for r in rows]
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    for r in rows:
        print(r.date, r.signal, r.value, "| 공개", r.published_at)
    return rows


if __name__ == "__main__":
    main()
