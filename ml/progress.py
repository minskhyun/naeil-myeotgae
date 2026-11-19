"""실행 중에 무슨 일이 일어나는지 한 건씩 알린다 → 웹의 '분석 중' 화면이 지도 위에 그린다.

쓰는 법:   from ml import progress
          progress.emit("event", title="성수 팝업", lat=37.54, lon=127.05)
          progress.status("날씨 기록을 받는 중")

- 환경 변수 NM_PROGRESS=1 일 때만 표준 출력에 '@@EVENT {json}' 한 줄을 쓴다 (웹 서버가 run.py를 실행할 때 켠다).
  명령줄에서 그냥 돌릴 때는 화면이 지저분해지지 않게 아무것도 쓰지 않는다.
- 켜졌든 꺼졌든 EVENTS에 쌓아 두고, run.py가 끝날 때 progress.json으로 저장한다 (분석 과정 다시 보기).
- 예측 계산에는 아무 영향이 없다. 화면에 보여 줄 것을 알릴 뿐이다.

알림의 종류(kind)와 들어가는 값은 frontend/src/api.ts의 ProgressEvent와 맞춘다.
    step      단계 시작·끝          step(ingest|collect|evaluate|predict), status(start|done), note
    status    지금 하는 일 한 줄     text
    store     매장                 name, address, lat, lon
    sales     판매 기록             days, menus, first, last
    places    주변 시설             count, places[{name, group, lat, lon, distance_m}]
    plan      AI가 고른 정보원       method, model, radius_m, reason, picks[{what, name, lat, lon, reason}]
    weather   날씨                 days, first, last (가져온 기간)
    academic  학교 일정             days, first, last, exams·vacations·festivals(각각 몇 번)
    event     근처 행사             title, place, lat, lon, start, end, source, url
    article   읽은 글               title, url
    special   기념일               date, name, relevance(1~5, LLM), menus[특히 관련 있는 메뉴], reason
    trend_span 검색량을 가져온 기간    menus, days, first, last
    trend     메뉴 검색량            menu, pct (예측 날짜 기준: 최근 7일이 그 전 4주보다 몇 % 늘었나)
    rating    행사 평가 (LLM)       title, scale(1~5), relevance(1~5), distance_m, menus[특히 관련 있는 메뉴], reason
    trial     검증 중 시험 한 번     groups[정보 묶음], wape
    decision  정보를 쓸지 판정        group, adopted, reason
    scores    검증 결과             model, wape, base_wape, coverage, test_days
    forecast  내일 예측             date, menus, top[{menu, prep, pred}], warnings[문장]
"""
import json
import os
import sys
import threading
from pathlib import Path

PREFIX = "@@EVENT "                  # 이 글자로 시작하는 출력 줄이 알림이다 (backend/app/main.py가 골라낸다)
EVENTS: list[dict] = []              # 이번 실행에서 알린 것 전부
_LOCK = threading.Lock()             # 정보원 여러 개가 동시에 알려도 한 줄씩 온전히 나가게


def emit(kind: str, **data) -> None:
    event = {"kind": kind, **{k: v for k, v in data.items() if v is not None}}
    with _LOCK:
        EVENTS.append(event)
        if os.environ.get("NM_PROGRESS") == "1":
            sys.stdout.write(PREFIX + json.dumps(event, ensure_ascii=True, default=str) + "\n")    # 영문자만 → 글자 깨짐 걱정 없음
            sys.stdout.flush()


def status(text: str) -> None:
    """지금 하는 일을 한 줄로."""
    emit("status", text=text)


def reset() -> None:
    EVENTS.clear()


def save(path: Path) -> None:
    Path(path).write_text(json.dumps(EVENTS, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
