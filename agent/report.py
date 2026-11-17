"""주변 정보 수집 결과 요약 → sources_report.json  (화면의 '주변 정보' 탭이 읽는다)

"AI가 이 매장에 어떤 정보원을 왜 골랐고, 무엇을 얼마나 모았는지"를 사람이 볼 수 있게 한 파일로 모은다.
새로 계산하는 것은 없다. 이미 만들어진 파일을 읽어 요약만 한다.

읽는 파일 (모두 data/artifacts/{매장}/ 안. 없으면 그 부분은 비워 둔다)
    collectors/{store_id}_sources.json   정보원 선택 에이전트의 계획과 이유 (backend/collectors/agent.py가 만듦)
    collectors/{store_id}_nearby.json    에이전트가 살펴본 주변 시설
    signals.csv                          모은 신호 → 신호마다 며칠치·기간·출처
    collection.json                      모은 행사·뉴스 원문 → 제목·날짜·주소 (본문은 뺌)
"""
import datetime as dt
import json
from pathlib import Path

from agent.collectors_bridge import OBSERVED_PROXY
from contracts.schemas import ArticleSummary, SignalSummary, SourceReport
from ml.features import load_signals

REPORT_FILE = "sources_report.json"
PROXY_NOTE = "지난 날짜는 그때의 예보를 구할 수 없어 실제 관측값을 예보 대신 썼습니다"


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _signals(path: Path) -> list[SignalSummary]:
    """signals.csv → 신호마다 한 줄 (값이 있는 날 수, 기간, 가장 많이 쓰인 출처)."""
    if not path.exists():
        return []
    out = []
    for name, g in load_signals(path).groupby("signal"):
        urls = g["source_url"].astype(str)
        out.append(SignalSummary(
            signal=name, n_days=g["date"].nunique(), first_date=g["date"].min().date(), last_date=g["date"].max().date(),
            n_menus=g["menu"].nunique(),                                   # 매장 전체 신호는 0
            source_url=urls.str.replace(OBSERVED_PROXY, "", regex=False).mode().iloc[0] or None,
            note=PROXY_NOTE if urls.str.contains(OBSERVED_PROXY, regex=False).any() else None))
    return out


def _articles(path: Path) -> list[ArticleSummary]:
    """collection.json → 글마다 한 줄 (여러 날에 걸친 행사는 날짜 범위로 묶음), 최근 날짜부터."""
    by_article: dict[tuple, ArticleSummary] = {}
    for item in _read_json(path) or []:
        day = dt.date.fromisoformat(item["date"])
        key = (item["source_url"], item["title"])
        if key not in by_article:
            by_article[key] = ArticleSummary(title=item["title"], source_url=item["source_url"], first_date=day,
                                             last_date=day, published_at=item.get("published_at"))
        a = by_article[key]
        a.first_date, a.last_date = min(a.first_date, day), max(a.last_date, day)
    return sorted(by_article.values(), key=lambda a: a.first_date, reverse=True)


def build_report(store_id: str, out: Path, notes: list[str]) -> SourceReport:
    """매장 결과 폴더(out)의 파일들 + 수집 메모 → SourceReport."""
    nearby = _read_json(out / "collectors" / f"{store_id}_nearby.json")
    return SourceReport(
        store_id=store_id, generated_at=dt.datetime.now().replace(microsecond=0),
        plan=_read_json(out / "collectors" / f"{store_id}_sources.json"),
        n_nearby=len(nearby["places"]) if nearby else None,
        signals=_signals(out / "signals.csv"), articles=_articles(out / "collection.json"), notes=notes)


def write_report(store_id: str, out: Path, notes: list[str]) -> Path:
    path = out / REPORT_FILE
    path.write_text(build_report(store_id, out, notes).model_dump_json(indent=1), encoding="utf-8")
    return path
