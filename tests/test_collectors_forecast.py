"""단기예보 수집: 오늘 날씨를 어제 17시 발표분으로 채우는지 (네트워크 없이)."""
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))   # 수집기는 backend/에서 'collectors'로 import
from collectors.forecast import KST, daily_summary, with_today  # noqa: E402


def hourly(day: str, temp: float, hours=range(24)) -> list[dict]:
    """하루치 시간별 예보 항목 (기온만)."""
    return [dict(fcstDate=day, fcstTime=f"{h:02d}00", category="TMP", fcstValue=str(temp)) for h in hours]


def test_today_comes_from_yesterdays_17h_issue():
    now = dt.datetime(2026, 11, 20, 9, 30, tzinfo=KST)
    # 오늘 08시 발표: 오늘은 09시부터만 있다 → 오늘은 버려지고 내일만 남는다
    latest = daily_summary(hourly("20261120", 3.0, range(9, 24)) + hourly("20261121", -1.0))
    assert list(latest) == ["2026-11-21"]

    asked = []

    def fetch(base):                                   # D-1일 17시 발표분: D일과 D+1일이 들어 있다
        asked.append(base)
        d1, d2 = base.date() + dt.timedelta(days=1), base.date() + dt.timedelta(days=2)
        return hourly(f"{d1:%Y%m%d}", -0.5 if d1.day == 20 else 1.6) + hourly(f"{d2:%Y%m%d}", -2.0)

    forecast, issued = dict(latest), {d: "2026-11-20T08:00:00+09:00" for d in latest}
    with_today(forecast, issued, fetch, now)

    assert asked == [dt.datetime(2026, 11, day, 17, 0, tzinfo=KST) for day in (19, 18, 17)]
    assert forecast["2026-11-20"]["temp_mean"] == -0.5
    assert issued["2026-11-20"] == "2026-11-19T17:00:00+09:00"          # 어제 영업 종료 전에 알 수 있던 값
    assert forecast["2026-11-19"]["temp_mean"] == 1.6                    # 관측 자료가 아직 없는 어제도 채운다
    assert issued["2026-11-19"] == "2026-11-18T17:00:00+09:00"
    assert forecast["2026-11-21"]["temp_mean"] == -1.0                    # 내일은 최신 발표 그대로
    assert issued["2026-11-21"] == "2026-11-20T08:00:00+09:00"


def test_today_stays_empty_when_old_issue_fails():
    def fetch(base):
        raise RuntimeError("단기예보 API 오류")

    forecast, issued = {"2026-11-21": {"temp_mean": 1.0}}, {"2026-11-21": "x"}
    with_today(forecast, issued, fetch, dt.datetime(2026, 11, 20, 9, 30, tzinfo=KST))
    assert list(forecast) == ["2026-11-21"]
