"""대학 학사일정 수집: 페이지 원문 저장 -> LLM 추출 -> 원문 대조 -> events.json, external_daily.csv

backend 폴더에서 실행:
    python -m collectors.academic

원문은 data/raw/academic/{school}_{label}.txt 에 저장한다. 이 파일이 이미 있으면
다시 내려받지 않으므로, 자동으로 못 가져오는 페이지는 브라우저에서 복사해
같은 이름의 txt 로 저장해 두면 된다.
"""
import argparse
import csv
import datetime as dt
import json
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from collectors.llm import llm_json
from collectors.store import DAILY_FILE, EVENTS_FILE, get_store, plan_schools

HERE = Path(__file__).parent
SOURCES_FILE = HERE / "academic_sources.json"
RAW_DIR = Path("data/raw/academic")
KST = dt.timezone(dt.timedelta(hours=9))
CATEGORIES = {"exam", "festival", "semester_start", "semester_end", "vacation_start"}
DAILY_COLUMNS = ["exam_period", "vacation", "festival"]

PROMPT = """아래는 한국 대학 학사일정 페이지의 텍스트다. 이 페이지는 {hint} 일정이다.
다음 다섯 종류에 해당하는 일정만 골라 JSON 배열로 출력하라.

- exam: 중간시험, 기말시험(학기말 시험). 성적 입력·제출, 시험 관련 신청은 제외
- festival: 학생 축제, 문화제. 미사·예배·기념식·학위수여식·입학식은 제외
- semester_start: 정규 학기 개강일. 계절학기 개강은 제외
- semester_end: 정규 학기 종강일. 계절학기 종강, 종강미사는 제외
- vacation_start: 여름방학·겨울방학 시작일

각 항목 형식: {{"title": "...", "category": "...", "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD"}}

규칙:
- title 은 페이지에 적힌 표현을 한 글자도 바꾸지 말고 그대로 옮긴다.
- 하루짜리 일정은 start_date 와 end_date 를 같게 쓴다.
- 모든 날짜는 {range_start} 부터 {range_end} 사이여야 한다. 이 범위에 맞게 연도를 정한다.
- 한 줄에 여러 일정이 쉼표로 묶여 있으면 해당하는 부분만 title 로 쓴다.
- 페이지에 없는 일정은 만들지 않는다. 해당 일정이 없으면 빈 배열을 출력한다.

페이지 텍스트:
{text}
"""


def fetch_text(url: str) -> str:
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) naeil-myeotgae-collector"}
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or resp.encoding
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    lines = [ln.strip() for ln in soup.get_text("\n").splitlines()]
    return "\n".join(ln for ln in lines if ln)


def raw_path(source: dict) -> Path:
    return RAW_DIR / f"{source['school']}_{source['label']}.txt"


def load_raw(source: dict, refresh: bool) -> str:
    """원문 텍스트를 돌려준다. 저장된 파일이 있으면 그것을 쓴다."""
    path = raw_path(source)
    if path.exists() and not refresh:
        return path.read_text(encoding="utf-8")
    text = fetch_text(source["url"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text


def fetched_time(source: dict) -> str:
    """원문 파일을 저장한 시각. 다시 실행해도 원문이 같으면 바뀌지 않는다."""
    mtime = raw_path(source).stat().st_mtime
    return dt.datetime.fromtimestamp(mtime, KST).isoformat(timespec="seconds")


def _squash(s: str) -> str:
    return re.sub(r"\s+", "", s)


def extract(source: dict, text: str):
    """LLM 으로 일정을 뽑고, 원문에 실제로 있는 제목만 남긴다."""
    lo, hi = (dt.date.fromisoformat(d) for d in source["range"])
    items = llm_json(PROMPT.format(hint=source["hint"], range_start=lo, range_end=hi, text=text[:60000]))
    squashed = _squash(text)
    now = fetched_time(source)
    events = []
    for it in items:
        try:
            title = it["title"].strip()
            category = it["category"]
            start = dt.date.fromisoformat(it["start_date"])
            end = dt.date.fromisoformat(it["end_date"])
        except (KeyError, ValueError, AttributeError):
            print(f"  [skip] 형식 오류: {it}")
            continue
        if category not in CATEGORIES or start > end or (end - start).days > 60:
            print(f"  [skip] 범주·날짜 이상: {it}")
            continue
        if start < lo or end > hi:
            print(f"  [skip] 학기 범위를 벗어난 날짜: {title} {start}~{end}")
            continue
        if _squash(title) not in squashed:
            print(f"  [skip] 원문에 없는 제목: {title}")
            continue
        events.append({
            "event_id": f"{source['school']}-{start.isoformat()}-{category}",
            "source": "academic",
            "school": source["school"],
            "type": category,
            "title": title,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "source_url": source["url"],
            "published_at": None,   # 학사일정 페이지에는 게시 시각이 없다
            "fetched_at": now,
            "verified": True,
        })
    return events


def derive_vacations(events: list):
    """개강·종강·방학 시작일로 학교별 방학 기간을 만든다."""
    vacations = []
    for school in sorted({e["school"] for e in events}):
        mine = [e for e in events if e["school"] == school]
        day = lambda e: dt.date.fromisoformat(e["start_date"])
        starts = sorted(day(e) for e in mine if e["type"] == "semester_start")
        vstarts = {day(e): e for e in mine if e["type"] == "vacation_start"}
        # 방학 시작일이 따로 없는 학교는 종강 다음 날을 방학 시작으로 본다
        for e in mine:
            if e["type"] != "semester_end":
                continue
            cand = dt.date.fromisoformat(e["end_date"]) + dt.timedelta(days=1)
            if not any(abs((v - cand).days) <= 14 for v in vstarts):
                vstarts[cand] = e
        for v in sorted(vstarts):
            nxt = next((s for s in starts if s > v), None)
            if nxt is None or (nxt - v).days > 100:
                print(f"  [warn] {school} {v} 방학의 다음 개강일을 못 찾음 (다음 학기 페이지 필요)")
                continue
            base = vstarts[v]
            vacations.append({
                "event_id": f"{school}-{v.isoformat()}-vacation",
                "source": "academic",
                "school": school,
                "type": "vacation",
                "title": f"방학 ({base['title']} 기준)",
                "start_date": v.isoformat(),
                "end_date": (nxt - dt.timedelta(days=1)).isoformat(),
                "source_url": base["source_url"],
                "published_at": None,
                "fetched_at": base["fetched_at"],
                "verified": True,
            })
    return vacations


def daily_counts(events: list, schools=None):
    """날짜별로 시험·방학·축제 중인 학교 수를 센다. schools 가 있으면 그 학교만 센다."""
    type_to_col = {"exam": "exam_period", "vacation": "vacation", "festival": "festival"}
    active = {}  # (date, col) -> set(school)
    for e in events:
        col = type_to_col.get(e["type"])
        if not col or (schools is not None and e.get("school") not in schools):
            continue
        d = dt.date.fromisoformat(e["start_date"])
        end = dt.date.fromisoformat(e["end_date"])
        while d <= end:
            active.setdefault((d.isoformat(), col), set()).add(e["school"])
            d += dt.timedelta(days=1)
    return {k: len(v) for k, v in active.items()}


def update_events_json(path: Path, events: list):
    """학사일정 항목만 갈아 끼우고, 다른 수집기가 넣은 항목은 그대로 둔다."""
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    kept = [e for e in old if e.get("source") != "academic"]
    merged = kept + sorted(events, key=lambda e: (e["start_date"], e["school"], e["type"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")


def update_daily_csv(path: Path, counts: dict):
    if not path.exists():
        print(f"  [warn] {path} 가 없어 CSV 는 건너뜀. build_external_daily 를 먼저 실행하세요.")
        return
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames) + [c for c in DAILY_COLUMNS if c not in reader.fieldnames]
        rows = list(reader)
    for row in rows:
        for col in DAILY_COLUMNS:
            row[col] = counts.get((row["date"], col), 0)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="저장된 원문을 무시하고 다시 내려받기")
    parser.add_argument("--events", default=EVENTS_FILE)
    parser.add_argument("--daily", default=DAILY_FILE)
    parser.add_argument("--store", default=None)
    args = parser.parse_args()
    store = get_store(args.store)
    schools = plan_schools(store["store_id"])

    sources = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    events = []
    for src in sources:
        name = f"{src['school']} {src['label']}"
        try:
            text = load_raw(src, args.refresh)
        except requests.RequestException as err:
            print(f"[fail] {name}: 페이지를 못 가져옴 ({err.__class__.__name__})")
            continue
        if "시험" not in text:
            print(f"[fail] {name}: 원문에 일정이 안 보임. 브라우저에서 복사해 "
                  f"{RAW_DIR / (src['school'] + '_' + src['label'] + '.txt')} 로 저장하세요.")
            continue
        print(f"[..] {name}: LLM 추출 중 ({len(text)}자)", flush=True)
        try:
            found = extract(src, text)
        except RuntimeError as err:
            print(f"[fail] {name}: {err}")
            continue
        print(f"[ok] {name}: {len(found)}건")
        events.extend(found)

    # 같은 일정이 두 페이지에 걸쳐 나오면 한 번만 남긴다
    unique = {e["event_id"]: e for e in events}
    events = list(unique.values())
    events += derive_vacations(events)

    update_events_json(Path(args.events), events)
    update_daily_csv(Path(args.daily), daily_counts(events, schools))
    print(f"saved {args.events}: {len(events)} events")
    print("  CSV 반영 학교: " + (", ".join(schools) if schools is not None else "전체 (정보원 계획 없음)"))


if __name__ == "__main__":
    main()
