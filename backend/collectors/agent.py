"""정보원 탐색 에이전트: 매장 주변 시설을 보고 이 매장에 필요한 외부 정보원을 고른다.

LLM 이 고르고, 코드가 검증한다.
- 학교는 수집기가 있는 학교만, 그리고 주변 시설 목록에 실제로 있는 이름을 근거로 댄 경우만 인정
- 행사 반경은 300~2000m 로 제한
- 아직 수집기가 없는 정보원은 candidates 로 따로 남긴다 (다음에 만들 후보)
LLM 호출이 실패하면 거리 규칙으로 대신 정한다.

backend 폴더에서 실행 (collectors.kakao 다음에):
    python -m collectors.agent
결과: data/stores/{store_id}_sources.json
"""
import argparse
import datetime as dt
import json
from pathlib import Path

from collectors.llm import llm_json, model_name
from collectors.store import STORE_DIR, get_store, nearby_path, plan_path

KST = dt.timezone(dt.timedelta(hours=9))
SOURCES_FILE = Path(__file__).parent / "academic_sources.json"
SCHOOL_NAMES = {"yonsei": "연세대학교", "sogang": "서강대학교", "ewha": "이화여자대학교"}
SCHOOL_MAX_M = 3000
RADIUS_MIN, RADIUS_MAX = 300, 2000

PROMPT = """너는 소규모 외식 매장의 수요 예측을 돕는 데이터 분석가다.
아래 매장과 주변 시설 목록을 보고, 이 매장의 판매량에 영향을 줄 외부 정보원을 골라라.

[매장]
이름: {name}
업종: {category}

[주변 시설] (이름, 종류, 매장과의 거리)
{places}

[지금 수집할 수 있는 정보원]
1. 대학 학사일정: {schools}
   - 매장 손님에 그 학교 학생이 많을 것 같을 때만 고른다. 걸어서 오기 힘든 거리면 고르지 않는다.
2. 서울시 문화행사: 매장 반경 안에서 열리는 공연·축제·전시
   - 반경(radius_m)을 {rmin}~{rmax} 사이에서 정한다. 주변에 공연장·광장·관광지가 많을수록 넓게 잡는다.
3. 날씨: 모든 매장에 기본으로 쓴다.

[출력 형식] JSON 객체 하나:
{{
  "academic": [{{"school": "학교 코드", "evidence": "주변 시설 목록의 이름 그대로", "reason": "한 문장"}}],
  "events": {{"radius_m": 숫자, "evidence": ["주변 시설 이름", ...], "reason": "한 문장"}},
  "candidates": [{{"source": "아직 없는 정보원 이름", "evidence": "주변 시설 이름 그대로", "reason": "한 문장"}}]
}}

규칙:
- evidence 는 위 주변 시설 목록에 있는 이름을 한 글자도 바꾸지 말고 쓴다.
- 학교 코드는 {codes} 중에서만 쓴다.
- candidates 에는 목록에 없는 학교의 학사일정, 경기장 경기 일정, 공연장 공연 일정처럼
  지금은 수집할 수 없지만 이 매장에 중요해 보이는 정보원을 최대 5개 적는다.
"""


def available_schools():
    sources = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    return sorted({s["school"] for s in sources})


def format_places(places, limit=80):
    lines = []
    for p in places[:limit]:
        dist = f"{p['distance_m']}m" if p["distance_m"] is not None else "거리 모름"
        lines.append(f"- {p['name']} ({p['group']}, {dist})")
    return "\n".join(lines)


def validate(raw, places, schools):
    by_name = {p["name"]: p for p in places}
    notes = []

    academic = []
    for item in raw.get("academic", []) or []:
        code, ev = item.get("school"), item.get("evidence", "")
        place = by_name.get(ev)
        if code not in schools:
            notes.append(f"학교 코드 {code} 는 수집기가 없어 제외")
        elif place is None:
            notes.append(f"{code}: 근거 '{ev}' 가 주변 시설 목록에 없어 제외")
        elif SCHOOL_NAMES.get(code, code) not in ev:
            notes.append(f"{code}: 근거 '{ev}' 가 그 학교 시설이 아니어서 제외")
        elif place["distance_m"] is None or place["distance_m"] > SCHOOL_MAX_M:
            notes.append(f"{code}: '{ev}' 가 {SCHOOL_MAX_M}m 보다 멀어 제외")
        elif code not in [a["school"] for a in academic]:
            academic.append({"school": code, "evidence": ev, "distance_m": place["distance_m"],
                             "reason": item.get("reason", "")})

    ev_raw = raw.get("events") or {}
    try:
        radius = int(round(float(ev_raw.get("radius_m", 1000)) / 100) * 100)
    except (TypeError, ValueError):
        radius = 1000
    clamped = min(max(radius, RADIUS_MIN), RADIUS_MAX)
    if clamped != radius:
        notes.append(f"행사 반경 {radius}m 를 {clamped}m 로 조정")
    evidence = [e for e in ev_raw.get("evidence", []) or [] if e in by_name]
    events = {"radius_m": clamped, "evidence": evidence, "reason": ev_raw.get("reason", "")}

    candidates = []
    for c in (raw.get("candidates") or [])[:5]:
        if c.get("evidence") in by_name:
            candidates.append({"source": c.get("source", ""), "evidence": c["evidence"],
                               "distance_m": by_name[c["evidence"]]["distance_m"],
                               "reason": c.get("reason", "")})
    return academic, events, candidates, notes


def rule_based(places, schools):
    """LLM 을 못 쓸 때: 2km 안에 캠퍼스가 있는 학교, 행사 반경 1000m."""
    academic = []
    for code in schools:
        hits = [p for p in places if SCHOOL_NAMES.get(code, code) in p["name"]
                and p["distance_m"] is not None and p["distance_m"] <= 2000]
        if hits:
            near = min(hits, key=lambda p: p["distance_m"])
            academic.append({"school": code, "evidence": near["name"], "distance_m": near["distance_m"],
                             "reason": "2km 안에 캠퍼스가 있음 (거리 규칙)"})
    events = {"radius_m": 1000, "evidence": [], "reason": "기본값 (거리 규칙)"}
    return academic, events, []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", default=None)
    parser.add_argument("--rule", action="store_true", help="LLM 없이 거리 규칙으로만 정하기")
    args = parser.parse_args()

    store = get_store(args.store)
    npath = nearby_path(store["store_id"])
    if not npath.exists():
        raise SystemExit(f"{npath} 가 없습니다. python -m collectors.kakao 를 먼저 실행하세요.")
    nearby = json.loads(npath.read_text(encoding="utf-8"))
    places = nearby["places"]
    schools = available_schools()

    method, notes = "llm", []
    if args.rule:
        method = "rule"
    else:
        prompt = PROMPT.format(
            name=store["name"], category=store.get("category", ""), places=format_places(places),
            schools=", ".join(f"{c} ({SCHOOL_NAMES.get(c, c)})" for c in schools),
            codes=", ".join(schools), rmin=RADIUS_MIN, rmax=RADIUS_MAX)
        try:
            academic, events, candidates, notes = validate(llm_json(prompt), places, schools)
        except Exception as err:   # LLM 오류, JSON 형식 오류 모두 규칙으로 대신한다
            print(f"  [warn] LLM 판단 실패, 거리 규칙 사용: {err}")
            method = "rule"
    if method == "rule":
        academic, events, candidates = rule_based(places, schools)

    plan = {
        "store_id": store["store_id"],
        "created_at": dt.datetime.now(KST).isoformat(timespec="seconds"),
        "method": method,
        "model": model_name() if method == "llm" else "",
        "nearby_fetched_at": nearby.get("fetched_at"),
        "weather": {"use": True, "reason": "모든 매장 기본"},
        "academic": academic,
        "events": events,
        "candidates": candidates,
        "validation_notes": notes,
    }
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    out = plan_path(store["store_id"])
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"saved {out} ({method})")
    print("  학사일정: " + (", ".join(f"{a['school']}({a['distance_m']}m)" for a in academic) or "없음"))
    print(f"  행사 반경: {events['radius_m']}m")
    for c in candidates:
        print(f"  후보: {c['source']} ← {c['evidence']}")
    for n in notes:
        print(f"  [검증] {n}")


if __name__ == "__main__":
    main()
