"""매장·행사 주소 → 위도·경도.

- OpenStreetMap Nominatim (무료, 키 없음). 사용 규칙: 1초에 1번 이하, 앱 이름을 User-Agent로 밝힌다.
  → 모든 호출 사이를 MIN_GAP초 이상 띄운다. 일시적 실패(요청 너무 많음·서버 오류·시간 초과)는 잠깐 쉬고 다시 시도한다.
- 찾은 결과(못 찾은 것도)는 data/raw/geocode_cache.json에 저장 → 두 번째부터는 거의 바로 끝난다.
  (팝업 글 하나에 주소가 수십 개라 처음엔 몇 분 걸림, 11/17 리허설에서 7분)
- 한국 도로명 주소는 번지·건물 이름까지는 못 찾는 경우가 있어, 못 찾으면 뒤에서부터 한 단어씩 줄여 다시 찾는다
  ("서울 성동구 성수이로 75 도레미약국 성수점" → … → "서울 성동구 성수이로 75" → "서울 성동구 성수이로").
  날씨 예보 격자는 5km, 행사 '근처' 기준은 1km라서 거리 이름 수준 정확도면 대개 충분하다.
- 외부로 나가는 것은 가게·행사 주소뿐이다 (공개된 정보).
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "naeil-myeotgae/0.1 (hackathon prototype)"
MIN_GAP = 1.1                         # 호출 사이 최소 간격(초)
RETRIES = 3                           # 일시적 실패 때 다시 시도하는 횟수
CACHE_PATH = Path(__file__).resolve().parents[1] / "data" / "raw" / "geocode_cache.json"
_last_call = 0.0
_cache: dict[str, list | None] | None = None      # 주소 → [위도, 경도, 이름] 또는 None(못 찾음)


def _load() -> dict:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            _cache = {}
    return _cache


def _save():
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(_cache, ensure_ascii=False, indent=0), encoding="utf-8")


def _search(query: str) -> dict | None:
    global _last_call
    q = urllib.parse.urlencode(dict(q=query, format="json", limit=1, countrycodes="kr", **{"accept-language": "ko"}))
    req = urllib.request.Request(f"{URL}?{q}", headers={"User-Agent": USER_AGENT})
    for attempt in range(RETRIES):
        wait = MIN_GAP - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                hits = json.loads(r.read().decode("utf-8"))
            return hits[0] if hits else None
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            temporary = not isinstance(e, urllib.error.HTTPError) or e.code == 429 or e.code >= 500
            if not temporary or attempt == RETRIES - 1:
                raise
            time.sleep(5 * (attempt + 1))                  # 5초, 10초 쉬고 다시
        finally:
            _last_call = time.monotonic()
    return None


def geocode(address: str, search=_search) -> tuple[float, float, str]:
    """주소 → (위도, 경도, 찾은 이름). 끝까지 못 찾으면 ValueError."""
    address = " ".join(address.split())
    cache = _load()
    if address in cache:
        if cache[address] is None:
            raise ValueError(f"주소를 찾지 못했습니다(저장된 결과): {address!r}")
        lat, lon, name = cache[address]
        return lat, lon, name
    words = address.split()
    for n in range(len(words), 1, -1):                   # 최소 두 단어 (예: "서울 성동구")
        hit = search(" ".join(words[:n]))
        if hit:
            cache[address] = [float(hit["lat"]), float(hit["lon"]), hit.get("display_name", "")]
            _save()
            return tuple(cache[address])
    cache[address] = None                                 # 못 찾은 것도 저장 (다시 헛걸음하지 않게)
    _save()
    raise ValueError(f"주소를 찾지 못했습니다: {address!r} (구·동 이름까지 넣어 보세요)")
