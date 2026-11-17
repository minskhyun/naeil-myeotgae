"""매장 설정과 매장별 정보원 계획을 읽고 쓰는 공통 함수.

매장 목록: collectors/stores.json
주변 시설: data/stores/{store_id}_nearby.json   (collectors.kakao)
정보원 계획: data/stores/{store_id}_sources.json (collectors.agent)
"""
import json
import math
from pathlib import Path

STORES_FILE = Path(__file__).parent / "stores.json"
STORE_DIR = Path("data/stores")
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
