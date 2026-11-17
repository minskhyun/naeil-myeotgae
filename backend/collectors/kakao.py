"""카카오 로컬 API로 매장 좌표와 주변 시설을 조회한다.

backend 폴더에서 실행:
    python -m collectors.kakao                   # stores.json 의 첫 매장
    python -m collectors.kakao --store 매장ID

stores.json 에 address 가 있으면 좌표를 찾아 lat, lon 을 갱신한다.
결과: data/stores/{store_id}_nearby.json
"""
import argparse
import datetime as dt
import json
import os

import requests
from dotenv import load_dotenv

from collectors.store import STORE_DIR, get_store, load_stores, nearby_path, save_stores

BASE = "https://dapi.kakao.com/v2/local"
KST = dt.timezone(dt.timedelta(hours=9))

# 수요에 영향을 줄 만한 시설 종류
CATEGORIES = {
    "SC4": ("학교", 2000),
    "CT1": ("문화시설", 1500),
    "AT4": ("관광명소", 1500),
    "SW8": ("지하철역", 1000),
}
KEYWORDS = [("대학교", 3000), ("공연장", 2000), ("경기장", 3000), ("전시장", 2000)]
MAX_PAGES = 3  # 페이지당 15개, 종류별로 최대 45개


def _get(path, key, params):
    resp = requests.get(f"{BASE}{path}", headers={"Authorization": f"KakaoAK {key}"},
                        params=params, timeout=20)
    if resp.status_code != 200:
        raise RuntimeError(f"카카오 API 오류 {resp.status_code}: {resp.text[:200]}")
    return resp.json()


def geocode(address, key):
    """주소를 좌표로. 주소 검색이 안 되면 키워드 검색으로 한 번 더 찾는다."""
    for path in ("/search/address.json", "/search/keyword.json"):
        docs = _get(path, key, {"query": address, "size": 1})["documents"]
        if docs:
            return float(docs[0]["y"]), float(docs[0]["x"])
    raise RuntimeError(f"주소를 찾지 못했습니다: {address}")


def _collect(path, key, base_params):
    places = []
    for page in range(1, MAX_PAGES + 1):
        data = _get(path, key, {**base_params, "page": page, "size": 15, "sort": "distance"})
        places += data["documents"]
        if data["meta"].get("is_end", True):
            break
    return places


def fetch_nearby(lat, lon, key):
    found = {}
    xy = {"x": lon, "y": lat}
    jobs = [("/search/category.json", {"category_group_code": code, "radius": r}, label)
            for code, (label, r) in CATEGORIES.items()]
    jobs += [("/search/keyword.json", {"query": word, "radius": r}, word) for word, r in KEYWORDS]
    for path, params, label in jobs:
        for p in _collect(path, key, {**xy, **params}):
            if p["id"] in found:
                continue
            found[p["id"]] = {
                "id": p["id"],
                "name": p["place_name"],
                "category": p.get("category_name", ""),
                "group": p.get("category_group_name", "") or label,
                "distance_m": int(p["distance"]) if p.get("distance") else None,
                "lat": float(p["y"]),
                "lon": float(p["x"]),
                "url": p.get("place_url", ""),
            }
    return sorted(found.values(), key=lambda x: (x["distance_m"] is None, x["distance_m"] or 0))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", default=None)
    args = parser.parse_args()

    load_dotenv()
    key = os.environ.get("KAKAO_REST_KEY")
    if not key:
        raise SystemExit("backend/.env 에 KAKAO_REST_KEY 가 없습니다.")

    store = get_store(args.store)
    if store.get("address"):
        lat, lon = geocode(store["address"], key)
        stores = load_stores()
        for s in stores:
            if s["store_id"] == store["store_id"]:
                s["lat"], s["lon"] = round(lat, 6), round(lon, 6)
        save_stores(stores)
        store["lat"], store["lon"] = lat, lon
        print(f"[ok] 주소 좌표: {lat:.6f}, {lon:.6f}")

    places = fetch_nearby(store["lat"], store["lon"], key)
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    out = nearby_path(store["store_id"])
    out.write_text(json.dumps({
        "store_id": store["store_id"],
        "lat": store["lat"], "lon": store["lon"],
        "fetched_at": dt.datetime.now(KST).isoformat(timespec="seconds"),
        "places": places,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"saved {out}: 시설 {len(places)}곳")
    for p in [p for p in places if p["group"] in ("학교", "대학교") and "대학교" in p["name"]][:8]:
        print(f"  {p['distance_m']}m  {p['name']}")


if __name__ == "__main__":
    main()
