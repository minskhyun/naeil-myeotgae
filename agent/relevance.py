"""근처 행사를 '이 가게에 얼마나 영향을 줄 만한가'로 따진다 → 메뉴별 신호 event_impact.

행사라고 다 같지 않다: 3만 명 축제와 20명 북토크, 가게 앞 행사와 1km 밖 행사, 아이스 음료가 팔릴 야외 행사와
우리 메뉴와 상관없는 행사. 세 가지를 따진다.

    규모 (1~5)             LLM이 제목·분야·장소·글의 문장으로 추정
    거리                   코드가 계산 (가까움 = 1 − 거리/REACH_KM, 매장 바로 앞 1)
    가게와의 연관도 (1~5)   LLM이 가게 업종과 메뉴를 보고 추정. 특정 메뉴가 유난히 영향받으면 그 메뉴만 따로 매긴다

    event_impact(날짜, 메뉴) = 그날 열리는 근처 행사마다  (규모/5) × (그 메뉴의 연관도/5) × 가까움  을 더한 값

- LLM은 판매량을 예측하지 않는다. 행사의 성격을 1~5로 매길 뿐이고, 이 신호를 예측에 쓸지는 다른 신호처럼
  검증(ml/evaluate.py)이 정한다. 점수를 합치는 식은 event_weight 한 곳에 있다.
- 시점 규칙: 행사가 공개(등록)될 때마다 그날의 합이 한 줄씩 늘어난다. 예측 시각에는 그때까지 공개된 행사만 들어간다.
- 같은 행사는 다시 묻지 않는다 ({work_dir}/event_ratings.json). 새로 생긴 행사만 BATCH개씩 묶어 묻는다.
- 부르는 곳: agent/collect.py의 collect_all (정보원들이 찾은 행사 목록 job.found를 받아서)
"""
import datetime as dt
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydantic import BaseModel

from contracts.schemas import SignalRow, StoreConfig
from ml import progress
from ml.llm import ask

REACH_KM = 1.0             # 이 거리에서 가까움이 0이 된다 (그보다 먼 행사는 MIN_CLOSENESS)
MIN_CLOSENESS = 0.1        # 반경 끝의 행사도 조금은 센다
NEUTRAL = 3                # LLM 평가를 못 받은 행사에 주는 점수 (보통)
BATCH = 20                 # 한 번에 물어볼 행사 수 (답이 길어지면 느려지므로 나눠서, 동시에)
MAX_MENUS = 20             # LLM에 보여 줄 메뉴 수 (판매량 많은 순)
RATINGS_FILE = "event_ratings.json"
SHOWN = 10                 # 화면(분석 중)에 알릴 평가 수 (영향이 큰 것부터)

SYSTEM = """당신은 카페·베이커리 수요 예측 서비스의 '행사 평가' 담당입니다.
판매량을 예측하지 않습니다. 주어진 가게와 근처 행사 목록을 보고, 행사마다 아래 값만 매깁니다.

scale (1~5) 행사 규모. 글에 인원·규모가 적혀 있으면 그것을, 없으면 제목·분야·장소로 추정합니다.
  1 = 수십 명 이하 (소모임, 강좌, 북토크)
  2 = 수백 명 (작은 공연·전시)
  3 = 수천 명 (동네 단위 행사, 중소 팝업스토어, 중형 공연)
  4 = 1만 명 안팎 (인기 팝업, 페스티벌)
  5 = 수만 명 이상 (대형 축제·콘서트·마라톤, 도로 통제)

relevance (1~5) 이 가게의 손님 수에 영향을 줄 가능성.
  거리는 따로 계산하므로 여기서는 '어떤 사람들이 왜 오고, 오가는 길에 카페·베이커리에 들를 법한가'만 봅니다.
  1 = 거의 무관 (온라인 행사, 사전 예약한 소수만 참여, 참가자가 머물거나 돌아다니지 않음)
  3 = 보통
  5 = 매우 큼 (거리에서 열리는 야외 행사, 줄 서는 팝업, 이 가게와 같은 손님층이 몰림)

menus 가게 메뉴 중 이 행사로 '전체와 다르게' 영향받을 메뉴만 적습니다 (메뉴 이름은 목록에 있는 그대로, 점수 1~5).
  예: 한여름 야외 축제 → 아이스 음료 5. 어린이 행사 → 쿠키·케이크류 4, 커피 2. 특별히 다른 메뉴가 없으면 빈 목록.

reason 그렇게 본 이유 한 문장.

주어진 정보만으로 판단합니다. 행사가 실제로 어땠는지 아는 내용이 있어도 쓰지 않습니다. 모든 행사에 대해 id를 그대로 돌려줍니다."""


class MenuScore(BaseModel):
    menu: str
    score: int


class Rating(BaseModel):
    id: int
    scale: int
    relevance: int
    menus: list[MenuScore]
    reason: str


class RatingList(BaseModel):
    ratings: list[Rating]


def event_key(e: dict) -> str:
    """행사를 구별하는 이름표 (같은 행사는 다시 묻지 않으려고)."""
    return hashlib.sha256(f"{e['title']}|{e.get('place', '')}|{e['start']}|{e['end']}".encode()).hexdigest()[:16]


def _clamp(v: int) -> int:
    return max(1, min(5, int(v)))


def _ask_batch(store: StoreConfig, menus: list[str], batch: list[dict], cache_dir: Path) -> dict[str, dict]:
    """행사 몇 개를 LLM에 물어 {행사 이름표: 평가}로. 메뉴 이름이 목록에 없는 것은 버린다."""
    user = json.dumps(dict(
        store=dict(name=store.name or store.store_id, category=store.category, address=store.address),
        menus=menus,
        events=[dict(id=i, title=e["title"], place=e.get("place"), category=e.get("category"), period=f"{e['start']} ~ {e['end']}",
                     distance_m=round(e["distance_km"] * 1000), text=e.get("snippet")) for i, e in enumerate(batch)],
    ), ensure_ascii=False)
    out = {}
    for r in ask(SYSTEM, user, RatingList, cache_dir, max_tokens=8000).ratings:
        if 0 <= r.id < len(batch):
            out[event_key(batch[r.id])] = dict(
                scale=_clamp(r.scale), relevance=_clamp(r.relevance), reason=r.reason,
                menus={m.menu: _clamp(m.score) for m in r.menus if m.menu in menus})
    return out


def rate(store: StoreConfig, menus: list[str], events: list[dict], work_dir: Path) -> tuple[dict[str, dict], list[str]]:
    """행사마다 규모·연관도를 매긴다 → ({행사 이름표: 평가}, 메모). 이미 매긴 행사는 저장된 것을 쓴다."""
    path = Path(work_dir) / RATINGS_FILE
    ratings = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    new = list({event_key(e): e for e in events if event_key(e) not in ratings}.values())
    notes = []
    if new:
        batches = [new[i:i + BATCH] for i in range(0, len(new), BATCH)]

        def one(batch):
            try:
                return _ask_batch(store, menus[:MAX_MENUS], batch, Path(work_dir) / "llm_cache_ratings")
            except Exception as e:                           # 이 묶음만 평가 없이 (보통 점수로) 진행
                notes.append(f"행사 평가 일부 실패({type(e).__name__}) → {len(batch)}건은 보통 점수로 계산")
                return {}

        with ThreadPoolExecutor(min(4, len(batches))) as pool:
            for got in pool.map(one, batches):
                ratings.update(got)
        Path(work_dir).mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(ratings, ensure_ascii=False, indent=1), encoding="utf-8")
    notes.insert(0, f"행사 평가 {len(events)}건 (새로 물은 것 {len(new)}건)")
    return ratings, notes


def event_weight(scale: int, relevance: int, distance_km: float) -> float:
    """행사 하나가 한 메뉴에 주는 무게: 규모 × 연관도 × 가까움 (각각 0~1).  ★ 식을 바꾸려면 여기만."""
    closeness = max(MIN_CLOSENESS, 1 - distance_km / REACH_KM)
    return (scale / 5) * (relevance / 5) * closeness


def impact_rows(store_id: str, events: list[dict], ratings: dict[str, dict], menus: list[str],
                start: dt.date, end: dt.date) -> list[SignalRow]:
    """행사·평가 → 날짜·메뉴별 event_impact 줄. 행사가 공개될 때마다 그날의 합이 한 줄씩 늘어난다.
    취소 공지가 공개되면 그날 값은 0이 된다 (nearby_event와 같은 규칙: 가장 늦게 공개된 값이 쓰인다)."""
    by_day: dict[dt.date, list[dict]] = {}
    for e in events:
        day = max(e["start"], start)
        while day <= min(e["end"], end):
            by_day.setdefault(day, []).append(e)
            day += dt.timedelta(days=1)
    rows = []
    for day, todays in sorted(by_day.items()):
        todays.sort(key=lambda e: (e["published_at"], event_key(e)))
        total = dict.fromkeys(menus, 0.0)
        for i, e in enumerate(todays):
            r = ratings.get(event_key(e), {})
            # 공개 시각이 같은 행사가 더 있으면 다 더한 뒤 한 줄만 쓴다 (같은 시각의 줄이 여럿이면 어느 것이 '마지막'인지 모호하므로)
            last_of_moment = i + 1 == len(todays) or todays[i + 1]["published_at"] != e["published_at"]
            for m in menus:
                if e.get("cancelled"):
                    total[m] = 0.0
                else:
                    score = r.get("menus", {}).get(m, r.get("relevance", NEUTRAL))      # 메뉴별 점수가 없으면 가게 전체 점수
                    total[m] += event_weight(r.get("scale", NEUTRAL), score, e["distance_km"])
                if last_of_moment:
                    rows.append(SignalRow(date=day, store_id=store_id, signal="event_impact", menu=m, value=round(total[m], 4),
                                          source_url=e.get("url") or "", published_at=e["published_at"], kind="event"))
    return rows


def event_impact(store: StoreConfig, menus: list[str], events: list[dict], start: dt.date, end: dt.date,
                 work_dir: Path) -> tuple[list[SignalRow], list[str]]:
    """정보원들이 찾은 근처 행사 → (event_impact 줄, 메모). 행사나 메뉴가 없으면 아무것도 하지 않는다 (LLM도 안 부름)."""
    events = [e for e in events if e["end"] >= start and e["start"] <= end]
    if not events or not menus:
        return [], []
    progress.status(f"근처 행사 {len(events)}건이 우리 가게·메뉴와 얼마나 관련 있는지 AI가 따져 보는 중")
    ratings, notes = rate(store, menus, events, work_dir)
    live = [e for e in events if not e.get("cancelled") and event_key(e) in ratings]
    live.sort(key=lambda e: -event_weight(ratings[event_key(e)]["scale"], ratings[event_key(e)]["relevance"], e["distance_km"]))
    for e in live[:SHOWN]:                                   # 화면: 영향이 큰 행사부터 평가 결과
        r = ratings[event_key(e)]
        progress.emit("rating", title=e["title"], scale=r["scale"], relevance=r["relevance"], reason=r["reason"],
                      distance_m=round(e["distance_km"] * 1000),
                      menus=[m for m, s in r["menus"].items() if s >= max(4, r["relevance"])])    # 특히 관련 깊은 메뉴만
    return impact_rows(store.store_id, events, ratings, menus, start, end), notes
