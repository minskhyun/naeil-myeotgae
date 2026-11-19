"""매장 하나의 주변 정보를 모두 모으는 입구.  run.py가 collect_all()을 부른다.

정보원 하나 = 함수 하나.  모두 같은 모양이다:
    함수(job) -> (신호 줄 목록, 원문 목록, 메모 목록)
      신호 줄 (SignalRow)      → signals.csv     → 예측 모델의 입력 후보 (검증에서 도움이 될 때만 채택)
      원문 (CollectionItem)    → collection.json → AI 주의 안내의 재료 (숫자는 안 바꿈)
      메모                     → 실행 기록에 한 줄씩 (무엇을 몇 건 모았는지, 왜 건너뛰었는지)

정보원들이 끝나면, 찾은 근처 행사를 한데 모아 '이 가게에 얼마나 영향을 줄 만한가'를 따진다 (agent/relevance.py → event_impact).

★ 정보원을 늘리려면: 아래에 함수를 하나 만들고 SOURCES에 한 줄 추가한다.
  함수가 실패(예외)해도 collect_all이 메모만 남기고 나머지 정보원으로 계속한다.

    정보원                       실제 일을 하는 파일
    public_data   날씨·학사일정·서울 문화행사   backend/collectors (새얼) + agent/collectors_bridge.py
    special_days  기념일                      agent/special_days.py
    event_posts   뉴스·블로그·공지의 행사       agent/naver.py(검색) → agent/events.py(LLM 추출) → agent/geocode.py(거리)
    menu_trend    메뉴 검색량 유행             agent/naver.py
"""
import datetime as dt
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from agent import collectors_bridge, events, naver, relevance
from agent.special_days import special_day_signals
from contracts.schemas import CollectionItem, SignalRow, StoreConfig
from ml import progress
from ml.paths import RAW

Result = tuple[list[SignalRow], list[CollectionItem], list[str]]
EVENT_LLM_CACHE = RAW / "llm_cache_events"     # 행사 글 LLM 응답 저장 (같은 글은 다시 부르지 않음, 매장끼리 공유)


@dataclass
class CollectJob:
    """수집 한 번에 필요한 것."""
    store: StoreConfig                 # 매장 설정 (주소·좌표가 있어야 함)
    start: dt.date                     # 이 날짜부터
    end: dt.date                       # 이 날짜까지의 정보를 모은다
    work_dir: Path                     # 공공 데이터 수집기의 결과 폴더 (data/artifacts/{매장}/collectors)
    sources_path: Path | None = None   # 사람이 모은 행사 글 주소 파일 (선택)
    target: dt.date | None = None      # 예측 날짜 (메뉴 검색량 안내를 붙일 날)
    menus: list[str] = field(default_factory=list)   # 판매량 많은 순 메뉴 이름
    found: list[dict] = field(default_factory=list)  # 정보원들이 찾은 근처 행사 (agent/relevance.py가 규모·연관도를 따진다)


# ---------------------------------------------------------------- 정보원

def public_data(job: CollectJob) -> Result:
    """공공 데이터 수집기: 날씨(과거 = 관측값 대용, 앞으로 = 실제 예보), 학사일정, 서울 문화행사."""
    store_id = job.store.store_id
    collectors_bridge.ensure_store(job.store, job.work_dir)
    yesterday = dt.date.today() - dt.timedelta(days=1)
    ok, tail = collectors_bridge.run_collectors(store_id, job.start, yesterday, job.work_dir)
    if not ok:
        return [], [], ["공공 데이터 수집 실패 → 날씨·학사일정·서울 행사 없이 진행: " + " / ".join(tail[-2:])]
    rows, items, notes = collectors_bridge.signals_from_collectors(store_id, job.start, job.end, job.work_dir)
    job.found.extend(collectors_bridge.nearby_events(store_id, job.work_dir, job.start, job.end))
    collectors_bridge.tell_results(store_id, job.work_dir, rows, job.target or job.end)
    return rows, items, notes


def special_days(job: CollectJob) -> Result:
    """발렌타인·빼빼로데이·크리스마스 같은 기념일: 당일·앞둔 날 표시 + 기념일마다, 메뉴마다의 연관도(LLM이 1~5로)."""
    rows = special_day_signals(job.store.store_id, job.start, job.end)
    more, notes = relevance.special_impact(job.store, job.menus, job.start, job.end, job.work_dir)
    return rows + more, [], notes


def event_posts(job: CollectJob) -> Result:
    """행사 글(사람이 모은 주소 + 네이버 뉴스·블로그 검색) → LLM이 날짜·장소 추출 → 매장 근처 행사만."""
    notes = []
    sources = events.read_sources(job.sources_path) if job.sources_path and Path(job.sources_path).exists() else []
    if naver.has_keys():
        try:
            found, n = naver.news_sources(naver.area_keywords(job.store))
            known = {url for url, _ in sources}
            sources += [s for s in found if s[0] not in known]
            notes += n
        except Exception as e:
            notes.append(f"네이버 검색 실패({type(e).__name__})")
    else:
        notes.append("네이버 검색 건너뜀(.env에 NAVER_CLIENT_ID·SECRET 없음)")
    if not sources:
        return [], [], notes
    rows, items, n = events.page_event_signals(job.store.store_id, job.store.lat, job.store.lon, sources,
                                               job.start, job.end, EVENT_LLM_CACHE, found=job.found)
    return rows, items, notes + n + [f"행사 글 {len(sources)}개에서 행사 {len({r.date for r in rows})}일"]


def menu_trend(job: CollectJob) -> Result:
    """메뉴 이름의 네이버 검색량 → 메뉴별 유행 신호(trend_level) + 크게 바뀐 메뉴는 AI 주의 안내 원문."""
    if not (naver.has_keys() and job.target and job.menus):
        return [], [], []
    return naver.menu_trend(job.store.store_id, job.menus, job.start, job.target)


SOURCES = [("공공 데이터", public_data), ("기념일", special_days), ("행사 글", event_posts), ("메뉴 검색량", menu_trend)]
# 정보원을 시작할 때 화면에 보여 줄 '지금 하는 일' (ml/progress.py)
SOURCE_TEXT = {"공공 데이터": "날씨·학교 일정·서울시 행사를 모으는 중", "기념일": "기념일을 확인하는 중",
               "행사 글": "근처 팝업·행사 소식을 뉴스와 블로그에서 찾는 중", "메뉴 검색량": "메뉴별 검색량(유행)을 확인하는 중"}


# ---------------------------------------------------------------- 한 번에

def collect_all(store: StoreConfig, start: dt.date, end: dt.date, work_dir: Path, sources_path: Path | None = None,
                target: dt.date | None = None, menus: list[str] | None = None) -> Result:
    """SOURCES의 정보원을 동시에 실행해 결과를 합친다. 하나가 실패해도 나머지는 계속한다.
    서로 다른 곳에서 정보를 받아 오는 일이라 동시에 해도 되고, 결과는 SOURCES 순서대로 합치므로 차례로 한 것과 같다."""
    job = CollectJob(store, start, end, Path(work_dir), sources_path, target, menus or [])

    def run(name, source):
        progress.status(SOURCE_TEXT.get(name, name))
        return source(job)

    with ThreadPoolExecutor(len(SOURCES)) as pool:
        waiting = [(name, pool.submit(run, name, source)) for name, source in SOURCES]
    rows, items, notes = [], [], []
    for name, done in waiting:
        try:
            r, i, n = done.result()
        except Exception as e:
            code = getattr(e, "code", "")                       # HTTP 오류면 상태 코드도 남긴다 (예: 429)
            notes.append(f"{name} 실패({type(e).__name__}{f' {code}' if code else ''}) → 이 정보 없이 진행")
            continue
        rows, items, notes = rows + r, items + i, notes + n
    try:                                # 찾은 행사를 규모·거리·가게(메뉴)와의 연관도로 따져 메뉴별 신호로 (LLM이 1~5로 매김)
        r, n = relevance.event_impact(store, job.menus, job.found, start, end, job.work_dir)
        rows, notes = rows + r, notes + n
    except Exception as e:
        notes.append(f"행사 평가 실패({type(e).__name__}) → 이 정보 없이 진행")
    return rows, items, notes
