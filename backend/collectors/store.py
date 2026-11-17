"""매장 설정과 매장별 정보원 계획을 읽고 쓰는 공통 함수. 결과 파일 위치도 여기서 정한다.

수집기만 따로 실행할 때 (backend 폴더에서, 저장소에 든 신촌 예시 매장)
    매장 목록: collectors/stores.json
    주변 시설: data/stores/{store_id}_nearby.json   (collectors.kakao)
    정보원 계획: data/stores/{store_id}_sources.json (collectors.agent)
    수집 결과: data/external_daily.csv, data/events.json

예측 엔진이 실행할 때 (run.py → agent/collectors_bridge.py)
    환경 변수 COLLECTORS_WORK_DIR=<매장별 폴더>를 주면 위 파일이 모두 그 폴더에 생긴다
    (stores.json, {store_id}_nearby.json, {store_id}_sources.json, external_daily.csv, events.json).
    → 실제 매장 결과가 저장소의 예시 파일을 덮어쓰지 않고, 매장끼리도 섞이지 않는다.
학사일정 원문(data/raw/academic)과 서울시 행사 원본(data/raw/seoul_culture)은 매장과 상관없어 늘 backend/data 에 둔다.
"""
import json
import math
import os
from pathlib import Path

WORK_DIR = Path(os.environ["COLLECTORS_WORK_DIR"]) if os.environ.get("COLLECTORS_WORK_DIR") else None
STORES_FILE = WORK_DIR / "stores.json" if WORK_DIR else Path(__file__).parent / "stores.json"
STORE_DIR = WORK_DIR or Path("data/stores")
DAILY_FILE = str(WORK_DIR / "external_daily.csv") if WORK_DIR else "data/external_daily.csv"
EVENTS_FILE = str(WORK_DIR / "events.json") if WORK_DIR else "data/events.json"
ENV_HINT = "프로젝트 맨 위 .env"          # 키가 없을 때 안내 문구에 쓴다
DEFAULT_EVENT_RADIUS_M = 1000


def load_stores():
    return json.loads(STORES_FILE.read_text(encoding="utf-8"))


def save_stores(stores):
    STORES_FILE.write_text(json.dumps(stores, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def get_store(store_id=None):
    stores = load_stores()
    if store_id is None:
        return stores[0]
    for s in stores:
        if s["store_id"] == store_id:
            return s
    raise SystemExit(f"stores.json 에 {store_id} 매장이 없습니다.")


def nearby_path(store_id):
    return STORE_DIR / f"{store_id}_nearby.json"


def plan_path(store_id):
    return STORE_DIR / f"{store_id}_sources.json"


def load_plan(store_id):
    """정보원 계획. 아직 없으면 None (그때는 수집기가 기본값을 쓴다)."""
    path = plan_path(store_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def plan_schools(store_id):
    """이 매장에 반영할 학교 목록. 계획이 없으면 None = 모든 학교."""
    plan = load_plan(store_id)
    if plan is None:
        return None
    return [s["school"] for s in plan.get("academic", [])]


def plan_event_radius(store_id):
    plan = load_plan(store_id)
    if plan and plan.get("events"):
        return plan["events"]["radius_m"]
    return DEFAULT_EVENT_RADIUS_M


def distance_m(lat1, lon1, lat2, lon2):
    """두 좌표 사이 거리 (미터)."""
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
