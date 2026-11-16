"""매장 주소 → 위도·경도 (날씨를 가져올 위치).

- OpenStreetMap Nominatim (무료, 키 없음). 사용 규칙: 1초에 1번 이하, 앱 이름을 User-Agent로 밝힌다.
- 한국 도로명 주소는 번지까지는 못 찾는 경우가 있어, 못 찾으면 뒤에서부터 한 단어씩 줄여 다시 찾는다
  ("서울 성동구 성수이로 113" → "서울 성동구 성수이로" → "서울 성동구").
  날씨 예보 격자가 5km라서 동·구 수준 정확도면 충분하다.
- 외부로 나가는 것은 가게 주소뿐이다 (공개된 정보).
"""
import json
import time
import urllib.parse
import urllib.request

URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "naeil-myeotgae/0.1 (hackathon prototype)"


def _search(query: str) -> dict | None:
    q = urllib.parse.urlencode(dict(q=query, format="json", limit=1, countrycodes="kr", **{"accept-language": "ko"}))
    req = urllib.request.Request(f"{URL}?{q}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=15) as r:
        hits = json.loads(r.read().decode("utf-8"))
    return hits[0] if hits else None


def geocode(address: str, search=_search) -> tuple[float, float, str]:
    """주소 → (위도, 경도, 찾은 이름). 끝까지 못 찾으면 ValueError."""
    words = address.split()
    for n in range(len(words), 1, -1):                   # 최소 두 단어 (예: "서울 성동구")
        hit = search(" ".join(words[:n]))
        if hit:
            return float(hit["lat"]), float(hit["lon"]), hit.get("display_name", "")
        time.sleep(1.1)                                   # 사용 규칙: 1초에 1번 이하
    raise ValueError(f"주소를 찾지 못했습니다: {address!r} (구·동 이름까지 넣어 보세요)")
