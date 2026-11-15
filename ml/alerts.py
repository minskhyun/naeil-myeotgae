"""LLM 특수 상황 경고 (TASKS.md §11, B안).  ★ 숫자는 바꾸지 않는다. 경고 문장만 만든다.

입력: 예측 날짜·메뉴별 예측, 모델이 이미 쓴 신호(signals_used), 새얼이 모은 collection.json의 그날 전후 항목
출력: Warning 리스트 (없으면 빈 리스트)

- 같은 입력은 다시 호출하지 않는다: 입력 해시로 llm_cache/에 저장 → 데모에서는 저장된 결과를 씀
- 코드가 거르는 것: 원문 인용(quote)이 그 출처의 실제 글에 그대로 없으면 버린다 (지어낸 인용 방지)
- LLM 제공자·모델은 .env에서 읽는다 (LLM_PROVIDER, LLM_MODEL). API 키는 코드·로그에 넣지 않는다.
- 제공자를 늘리려면 PROVIDERS에 함수 하나를 추가한다.

collection.json 형식(가정, 새얼과 확정 필요): [{"date": "2026-11-01", "title": "...", "text": "원문", "source_url": "..."}]
"""
import hashlib
import json
import os
from pathlib import Path

import pandas as pd
from pydantic import BaseModel

from contracts.schemas import Forecast, Warning

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = {"LLM_PROVIDER": "anthropic", "LLM_MODEL": "claude-opus-5-5"}
WINDOW_DAYS = 1            # 예측 날짜 ±1일의 항목만 넘긴다

SYSTEM = """당신은 카페·베이커리 판매 예측 서비스의 '특수 상황 경고' 담당입니다.
판매량 숫자를 만들거나 고치지 않습니다. 주어진 자료에서 예측 모델이 모르는 특별한 상황만 찾아 경고합니다.
규칙:
- 모델이 이미 쓴 신호(signals_used)와 같은 상황(예: 날씨 신호가 있으면 일반적인 비 예보)은 경고하지 않습니다.
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

def _payload(forecast: Forecast, collection: list[dict]) -> dict | None:
    target = pd.Timestamp(forecast.rows[0].date)
    items = []
    for it in collection:
        gap = (pd.Timestamp(it["date"]) - target).days
        if abs(gap) <= WINDOW_DAYS:
            items.append({**it, "days_from_forecast_date": gap})   # 날짜 차이는 코드가 계산해서 넘긴다
    if not items:
        return None
    return dict(
        forecast_date=str(target.date()),
        menus=[dict(menu=r.menu, pred=r.pred, p10=r.p10, p90=r.p90) for r in forecast.rows],
        signals_used=forecast.signals_used,
        items=items,
    )


def _quotes_are_real(w: Warning, items: list[dict]) -> bool:
    texts = {}
    for it in items:
        texts.setdefault(it["source_url"], []).append(it.get("title", "") + "\n" + it.get("text", ""))
    return all(any(e.quote in t for t in texts.get(e.source_url, [])) for e in w.evidence)


def make_warnings(forecast: Forecast, collection: list[dict], cache_dir: Path) -> list[Warning]:
    payload = _payload(forecast, collection)
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
    return [w for w in result.warnings if _quotes_are_real(w, payload["items"])]
