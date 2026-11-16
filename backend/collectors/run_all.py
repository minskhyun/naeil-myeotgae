"""외부 데이터 수집 전체를 올바른 순서로 실행한다.

backend 폴더에서 실행:
    python -m collectors.run_all                         # 2025-11-01 ~ 어제
    python -m collectors.run_all --start 2025-03-01
    python -m collectors.run_all --replan                # 주변 시설 조회와 정보원 선택부터 다시

순서: 주변 시설 → 정보원 선택 → 날씨·공휴일 → 예보 → 학사일정 → 행사
날씨·공휴일 단계가 external_daily.csv 를 새로 쓰므로 반드시 맨 앞에 와야 한다.
"""
import argparse
import datetime as dt
import subprocess
import sys

from collectors.store import get_store, nearby_path, plan_path


def run(module, *args, required=True):
    print(f"\n=== {module} ===", flush=True)
    code = subprocess.call([sys.executable, "-m", f"collectors.{module}", *args])
    if code != 0:
        if required:
            raise SystemExit(f"{module} 실패. 위 오류를 확인하세요.")
        print(f"[warn] {module} 실패, 이 단계 없이 계속합니다.")
    return code == 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", default=None)
    parser.add_argument("--start", default="2025-11-01")
    parser.add_argument("--end", default=(dt.date.today() - dt.timedelta(days=1)).isoformat())
    parser.add_argument("--replan", action="store_true")
    parser.add_argument("--refresh-events", action="store_true", help="서울시 행사 목록 새로 받기")
    args = parser.parse_args()

    store = get_store(args.store)
    sid = ["--store", store["store_id"]]

    if args.replan or not nearby_path(store["store_id"]).exists():
        run("kakao", *sid, required=False)
    if nearby_path(store["store_id"]).exists() and (args.replan or not plan_path(store["store_id"]).exists()):
        run("agent", *sid, required=False)

    run("build_external_daily", "--start", args.start, "--end", args.end)
    run("forecast", *sid, required=False)
    run("academic", *sid)
    run("seoul_events", *sid, *(["--refresh"] if args.refresh_events else []), required=False)
    print("\n완료: data/external_daily.csv, data/events.json")


if __name__ == "__main__":
    main()
