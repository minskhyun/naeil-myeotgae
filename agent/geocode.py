"""매장·행사 주소 → 위도·경도.

- OpenStreetMap Nominatim (무료, 키 없음). 사용 규칙: 1초에 1번 이하, 앱 이름을 User-Agent로 밝힌다.
  → 모든 호출 사이를 MIN_GAP초 이상 띄우고, 한 번 찾은 주소는 기억한다 (같은 건물이 여러 번 나와도 한 번만).
- 한국 도로명 주소는 번지·건물 이름까지는 못 찾는 경우가 있어, 못 찾으면 뒤에서부터 한 단어씩 줄여 다시 찾는다
  ("서울 성동구 성수이로 75 도레미약국 성수점" → … → "서울 성동구 성수이로 75" → "서울 성동구 성수이로").
  날씨 예보 격자는 5km, 행사 '근처' 기준은 1km라서 거리 이름 수준 정확도면 대개 충분하다.
- 외부로 나가는 것은 가게·행사 주소뿐이다 (공개된 정보).
"""
import json
import time
import urllib.parse
import urllib.request

URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "naeil-myeotgae/0.1 (hackathon prototype)"
MIN_GAP = 1.1                         # 호출 사이 최소 간격(초)
_last_call = 0.0
_memo: dict[str, tuple[float, float, str]] = {}


def _search(query: str) -> dict | None:
    global _last_call
    wait = MIN_GAP - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    q = urllib.parse.urlencode(dict(q=query, format="json", limit=1, countrycodes="kr", **{"accept-language": "ko"}))
    req = urllib.request.Request(f"{URL}?{q}", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            hits = json.loads(r.read().decode("utf-8"))
    finally:
        _last_call = time.monotonic()
    return hits[0] if hits else None


def geocode(address: str, search=_search) -> tuple[float, float, str]:
    """주소 → (위도, 경도, 찾은 이름). 끝까지 못 찾으면 ValueError."""
    address = " ".join(address.split())
    if address in _memo:
        return _memo[address]
    words = address.split()
    for n in range(len(words), 1, -1):                   # 최소 두 단어 (예: "서울 성동구")
        hit = search(" ".join(words[:n]))
        if hit:
            _memo[address] = float(hit["lat"]), float(hit["lon"]), hit.get("display_name", "")
            return _memo[address]
    raise ValueError(f"주소를 찾지 못했습니다: {address!r} (구·동 이름까지 넣어 보세요)")
