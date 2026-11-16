"""매장 하나의 외부 신호를 모아 signals.json 하나로 (run.py --signals에 그대로 넣는다).

    python -m agent.build --store seongsu-a --lat 37.5446 --lon 127.0557 --start 20260915
    → data/raw/seongsu-a_signals.json

모으는 것
  - 날씨(과거): ASOS 관측값을 예보 대신  (start ~ 어제)        ※ 실제 예보가 아님 → 발표·문서에 밝힐 것
  - 날씨(앞으로): 기상청 단기예보 17시 발표본 (내일·모레)      실제 예보가 있는 날짜는 관측값 대용 줄을 버린다
  - 기념일: special_day
행사(nearby_event)는 아직 없다 (events.py 예정). 출처를 늘리려면 collect()에 한 줄 추가한다.
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from contracts.schemas import SignalRow

ROOT = Path(__file__).resolve().parents[1]


def merge_weather(proxy: list[SignalRow], live: list[SignalRow]) -> list[SignalRow]:
    """실제 예보(live)가 있는 날짜는 관측값 대용(proxy) 줄을 버린다 (둘이 섞이지 않게)."""
    live_dates = {r.date for r in live}
    return [r for r in proxy if r.date not in live_dates] + live


def collect(store_id: str, lat: float, lon: float, start: str, key: str, today: dt.date | None = None) -> list[SignalRow]:
    from agent.special_days import special_day_signals
    from agent.weather import fetch_asos_daily, forecast_signals, observed_as_forecast_signals

    today = today or dt.date.today()
    yesterday = (today - dt.timedelta(days=1)).strftime("%Y%m%d")
    proxy = observed_as_forecast_signals(store_id, fetch_asos_daily(key, start, yesterday))
    # 최근 3일 발표본을 모두 남긴다 (오늘·어제 날짜 값은 어제·그제 발표본에 있다).
    # 같은 날짜에 여러 발표본이 있어도 features.attach_signals가 '예측 시각 전 가장 늦은 것' 하나만 쓴다.
    live = []
    for k in range(3):
        base = today - dt.timedelta(days=k)
        try:
            live += forecast_signals(store_id, lat, lon, base.strftime("%Y%m%d"), key)
        except RuntimeError as e:                               # 오늘 17시 발표 전 등
            print(f"  단기예보 {base} 17시 발표본 없음 ({e})")
    rows = merge_weather(proxy, live)
    rows += special_day_signals(store_id, dt.datetime.strptime(start, "%Y%m%d").date(), today + dt.timedelta(days=3))
    return rows


def main(argv=None) -> Path:
    from ml.alerts import settings
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="매장 외부 신호 → signals.json")
    p.add_argument("--store", required=True)
    p.add_argument("--lat", type=float, required=True)
    p.add_argument("--lon", type=float, required=True)
    p.add_argument("--start", required=True, help="신호 시작일 YYYYMMDD (POS 첫날 이전으로)")
    p.add_argument("--out", help="기본: data/raw/{store}_signals.json")
    a = p.parse_args(argv)
    key = settings().get("DATA_GO_KR_KEY")
    if not key:
        raise SystemExit(".env에 DATA_GO_KR_KEY가 없습니다.")
    rows = collect(a.store, a.lat, a.lon, a.start, key)
    out = Path(a.out or ROOT / "data" / "raw" / f"{a.store}_signals.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps([r.model_dump(mode="json") for r in rows], ensure_ascii=False, indent=1), encoding="utf-8")

    from agent.weather import OBSERVED_PROXY
    proxy = sum(OBSERVED_PROXY in r.source_url for r in rows)
    by_signal = {}
    for r in rows:
        by_signal[r.signal] = by_signal.get(r.signal, 0) + 1
    print(f"{out}  ({len(rows)}행: {by_signal})")
    print(f"  ※ 관측값을 예보 대신 쓴 줄 {proxy}행 — 검증 성능이 실제보다 조금 좋게 나올 수 있음 (발표·문서에 밝힐 것)")
    return out


if __name__ == "__main__":
    main()
