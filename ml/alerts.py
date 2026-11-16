"""LLM 특수 상황 경고 (TASKS.md §11, B안).  ★ 숫자는 바꾸지 않는다. 경고 문장만 만든다.

입력: 예측 날짜·메뉴별 예측, 모델이 이미 쓴 신호(signals_used), 새얼이 모은 collection.json의 그날 전후 항목
출력: Warning 리스트 (없으면 빈 리스트)

- 같은 입력은 다시 호출하지 않는다: 입력 해시로 llm_cache/에 저장 → 데모에서는 저장된 결과를 씀
- 코드가 거르는 것: 원문 인용(quote)이 그 출처의 실제 글에 그대로 없으면 버린다 (지어낸 인용 방지)
- LLM 제공자·모델은 .env에서 읽는다 (LLM_PROVIDER, LLM_MODEL). API 키는 코드·로그에 넣지 않는다.
- 제공자를 늘리려면 PROVIDERS에 함수 하나를 추가한다.

collection.json 형식: contracts.schemas.CollectionItem 목록
    [{"date": "2026-11-01", "title": "...", "text": "원문", "source_url": "...", "published_at": "2026-10-20T10:00:00+09:00"}]
LLM에 넘기기 전에 코드가 거르는 것: 예측 날짜 ±1일 밖, 예측 시각 뒤에 공개된 글(시점 규칙), 같은 글 중복.
원문은 앞 MAX_TEXT_CHARS자까지만 넘긴다.
"""
import hashlib
import json
import os
from pathlib import Path

import pandas as pd
from pydantic import BaseModel

from contracts.schemas import Forecast, Warning
from ml.features import DEFAULT_CLOSE_TIME, issue_time

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = {"LLM_PROVIDER": "anthropic", "LLM_MODEL": "claude-opus-5-5"}
WINDOW_DAYS = 1            # 예측 날짜 ±1일의 항목만 넘긴다
MAX_TEXT_CHARS = 3000      # 원문은 앞 3000자까지만 넘긴다 (비용·LLM 혼란 줄이기. 인용 검사도 잘린 글 기준)

SYSTEM = """당신은 카페·베이커리 판매 예측 서비스의 '특수 상황 경고' 담당입니다.
판매량 숫자를 만들거나 고치지 않습니다. 주어진 자료에서 예측 모델이 모르는 특별한 상황만 찾아 경고합니다.
규칙:
- model_already_reflected는 모델이 내일 예측에 이미 반영한 상황입니다(신호 이름: 근거 문장). 이와 같은 상황(예: 이미 반영된 비 예보)은 다시 경고하지 않습니다.
- signals_used는 모델이 쓸 수 있는 신호의 이름일 뿐입니다. 이름이 있어도 model_already_reflected에 없으면, 모델은 내일 그 상황을 모르는 것입니다 (예: nearby_event가 있어도 반영된 근거가 없으면 자료 속 행사는 모델이 모름).
- 모든 경고에는 자료 원문에서 그대로 복사한 인용(quote)과 그 출처(source_url)를 붙입니다. 원문에 없는 말은 인용하지 않습니다.
- 특별한 상황이 없으면 빈 목록을 돌려줍니다.
- message는 사장님께 보여 줄 쉬운 한국어 한 문장입니다. 숫자 예측을 쓰지 않습니다."""


class WarningList(BaseModel):
    warnings: list[Warning]


# ---------------------------------------------------------------- 설정·제공자

def settings() -> dict:
    """환경 변수 > .env 파일 > 기본값.  (.env는 'KEY=VALUE' 줄만 읽는다)"""
    found = dict(DEFAULTS)
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                found[k.strip()] = v.strip().strip('"')
    found.update({k: os.environ[k] for k in DEFAULTS if k in os.environ})
    return found


def _call_anthropic(model: str, user: str) -> WarningList:
    import anthropic                       # 경고 기능을 쓸 때만 필요 (pip install anthropic)
    if "ANTHROPIC_API_KEY" not in os.environ and (key := settings().get("ANTHROPIC_API_KEY")):
        os.environ["ANTHROPIC_API_KEY"] = key
    response = anthropic.Anthropic().messages.parse(
        model=model, max_tokens=16000, system=SYSTEM,
        messages=[{"role": "user", "content": user}], output_format=WarningList,
    )
    return response.parsed_output


PROVIDERS = {"anthropic": _call_anthropic}   # 이름 → 함수(model, user) -> WarningList


# ---------------------------------------------------------------- 경고 만들기

def _kst(t) -> pd.Timestamp:
    """'2026-10-20T10:00:00+09:00'·'...Z'·시간대 없는 시각 → 시간대 없는 한국 시간."""
    t = pd.Timestamp(t)
    return t.tz_convert("Asia/Seoul").tz_localize(None) if t.tzinfo is not None else t


def _payload(forecast: Forecast, collection: list[dict], close_time: str = DEFAULT_CLOSE_TIME) -> dict | None:
    target = pd.Timestamp(forecast.rows[0].date)
    issue = issue_time(target, close_time)                   # 예측을 내는 시각 (전날 영업 종료)
    items, seen = [], set()
    for it in collection:
        gap = (pd.Timestamp(it["date"]) - target).days
        if abs(gap) > WINDOW_DAYS:
            continue
        if it.get("published_at") and _kst(it["published_at"]) > issue:   # ★ 그때 몰랐던 글은 쓰지 않는다
            continue
        key = (it["source_url"], it.get("title", ""))
        if key in seen:                                          # 같은 글이 여러 번 모였으면 한 번만
            continue
        seen.add(key)
        items.append({**it, "text": str(it.get("text", ""))[:MAX_TEXT_CHARS],
                      "days_from_forecast_date": gap})          # 날짜 차이는 코드가 계산해서 넘긴다
    if not items:
        return None
    return dict(
        forecast_date=str(target.date()),
        menus=[dict(menu=r.menu, pred=r.pred, p10=r.p10, p90=r.p90) for r in forecast.rows],
        signals_used=forecast.signals_used,
        model_already_reflected=_reflected(forecast),
        items=items,
    )


def _reflected(forecast: Forecast) -> dict[str, str]:
    """모델이 내일 실제로 반영한 상황: 신호마다 효과가 가장 큰 메뉴의 근거 문장 하나 (예: rain_mm → '비 예보(9.7mm)로 …')."""
    best: dict[str, tuple[float, str]] = {}
    for r in forecast.rows:
        for x in r.reasons:
            if x.signal not in best or abs(x.effect_pct) > best[x.signal][0]:
                best[x.signal] = (abs(x.effect_pct), f"{x.text} (예: {r.menu})")
    return {k: v[1] for k, v in sorted(best.items())}


def _quotes_are_real(w: Warning, items: list[dict]) -> bool:
    texts = {}
    for it in items:
        texts.setdefault(it["source_url"], []).append(it.get("title", "") + "\n" + it.get("text", ""))
    return all(any(e.quote in t for t in texts.get(e.source_url, [])) for e in w.evidence)


def make_warnings(forecast: Forecast, collection: list[dict], cache_dir: Path,
                  close_time: str = DEFAULT_CLOSE_TIME) -> list[Warning]:
    payload = _payload(forecast, collection, close_time)
    if payload is None:                                        # 그날 전후 자료가 없으면 부르지 않는다
        return []
    cfg = settings()
    user = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    key = hashlib.sha256(f"{cfg['LLM_PROVIDER']}|{cfg['LLM_MODEL']}|{SYSTEM}|{user}".encode()).hexdigest()[:16]
    cache = Path(cache_dir) / f"{key}.json"
    if cache.exists():
        result = WarningList.model_validate_json(cache.read_text(encoding="utf-8"))
    else:
        result = PROVIDERS[cfg["LLM_PROVIDER"]](cfg["LLM_MODEL"], user)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(result.model_dump_json(indent=1), encoding="utf-8")
    kept = [w for w in result.warnings if _quotes_are_real(w, payload["items"])]
    menus = {r.menu for r in forecast.rows}
    for w in kept:          # 영향 메뉴: 예측에 있는 메뉴 이름만 남기고, 비면 전체(["*"]) — 계약의 약속
        w.menu_scope = [m for m in w.menu_scope if m in menus] or ["*"]
    return kept
