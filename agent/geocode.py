"""매장·행사 주소 → 위도·경도.

- 카카오 로컬(.env의 KAKAO_REST_KEY)을 먼저 쓴다: 주소 검색 → 안 되면 키워드 검색('올리브영 뷰티 맨션 성수' 같은 건물 이름).
  '한섬 EQL 성수, 서울 성동구 연무장15길 11'처럼 쉼표로 이어지면 부분마다 찾는다.
  카카오 키가 없거나 못 찾으면 아래 OpenStreetMap 방식으로.

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
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from ml.llm import settings
from ml.paths import RAW

URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "naeil-myeotgae/0.1 (hackathon prototype)"
MIN_GAP = 1.1                         # 호출 사이 최소 간격(초)
RETRIES = 3                           # 일시적 실패 때 다시 시도하는 횟수
CACHE_PATH = RAW / "geocode_cache.json"
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


KAKAO = "https://dapi.kakao.com/v2/local"


def _kakao(query: str) -> list | None:
    """카카오 로컬: 주소 검색 → 키워드 검색. 키가 없으면 None. 찾으면 [위도, 경도, 이름]."""
    key = settings().get("KAKAO_REST_KEY")
    if not key:
        return None
    for path in ("/search/address.json", "/search/keyword.json"):
        q = urllib.parse.urlencode({"query": query, "size": 1})
        req = urllib.request.Request(f"{KAKAO}{path}?{q}", headers={"Authorization": f"KakaoAK {key}"})
        with urllib.request.urlopen(req, timeout=15) as r:
            docs = json.loads(r.read().decode("utf-8"))["documents"]
        if docs:
            d = docs[0]
            return [float(d["y"]), float(d["x"]), d.get("place_name") or d.get("address_name", "")]
    return None


def place_queries(place: str) -> list[str]:
    """LLM이 적은 장소 → 카카오에 넣어 볼 검색어들 (정확한 것부터).
    "서울 성수동 '플레임그라운드(Flameground by BURGER KING)'" → ['플레임그라운드', ..., '서울 성수동 플레임그라운드', ...]
    '한섬 EQL 성수, 서울 성동구 연무장15길 11' → ['서울 성동구 연무장15길 11', ...]  (주소처럼 생긴 부분이 가장 정확)"""
    unparen = lambda s: re.sub(r"\([^)]*\)", " ", s)                                       # 괄호 안 설명 빼기
    out = []
    road = r"(?:서울(?:특별시)?\s+)?(?:[가-힣]+(?:시|구)\s+)*[가-힣0-9]+(?:로|길)\s*\d+(?:-\d+)?"
    for m in re.finditer(road, place):                                                       # 도로명 주소
        out.append(m.group(0))
    quoted = re.findall(r"['‘\"“]([^'’\"”]+)['’\"”]", place)                             # 따옴표 안 이름
    out += [unparen(q) for q in quoted] + quoted
    cleaned = " ".join(re.sub(r"['‘’\"“”]", " ", unparen(place)).split())
    out += [cleaned] + [p.strip() for p in cleaned.split(",") if p.strip()] + [place]
    seen = []
    for q in out:
        q = " ".join(re.sub(r"['‘’\"“”]", " ", q).split())
        if len(q) >= 2 and q not in seen:
            seen.append(q)
    return seen


def geocode(address: str, search=None) -> tuple[float, float, str]:
    """주소 → (위도, 경도, 찾은 이름). 끝까지 못 찾으면 ValueError.
    search를 주면(테스트) 카카오는 건너뛰고 그 함수로 OpenStreetMap 방식만 쓴다."""
    address = " ".join(address.split())
    cache = _load()
    if address in cache:
        if cache[address] is None:
            raise ValueError(f"주소를 찾지 못했습니다(저장된 결과): {address!r}")
        lat, lon, name = cache[address]
        return lat, lon, name
    if search is None:
        search = _search
        for part in place_queries(address):
            try:
                hit = _kakao(part)
            except Exception:
                hit = None                                 # 카카오 오류면 OpenStreetMap으로
            if hit:
                cache[address] = hit
                _save()
                return tuple(hit)
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
