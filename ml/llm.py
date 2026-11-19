"""설정(.env) 읽기와 LLM 호출을 한곳에 모은다.

쓰는 곳: ml/alerts.py(AI 주의 안내), agent/events.py(행사 글에서 날짜·장소 뽑기),
        agent/geocode.py·agent/naver.py(카카오·네이버 키만 읽음)
※ backend/collectors(정보원 선택·학사일정)는 따로 실행되는 묶음이라 자기 파일(collectors/llm.py)을 쓰지만, 같은 .env를 읽는다.

- settings(): 환경 변수 > 프로젝트 맨 위 .env > 기본값
- ask(): 답을 정해진 형식(pydantic 모델)으로 받고, 같은 질문은 다시 부르지 않는다 (입력 해시로 cache_dir에 저장)
         → 시연 때 결과가 바뀌지 않고, 비용도 한 번만 든다.
- 모델은 두 가지: LLM_MODEL(판단이 필요한 일: AI 주의 안내), LLM_MODEL_LIGHT(양이 많은 단순 추출: 행사 글).
  ask(..., light=True)면 가벼운 모델을 쓴다. 나눈 근거는 ml/REVIEW.md E '11/18 LLM 모델 비교'.
- 제공자를 늘리려면 PROVIDERS에 함수 하나를 추가한다. API 키는 코드·로그에 넣지 않는다.
"""
import hashlib
import os
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from ml.paths import ROOT

DEFAULTS = {"LLM_PROVIDER": "anthropic",
            "LLM_MODEL": "claude-opus-5-5",          # 판단이 필요한 일 (사장님이 직접 읽는 AI 주의 안내)
            "LLM_MODEL_LIGHT": "claude-haiku-5-5"}   # 양이 많은 단순 추출 (행사 글마다 한 번, 값이 Opus의 1/30)
KEY_NAMES = ("ANTHROPIC_API_KEY", "DATA_GO_KR_KEY", "SEOUL_DATA_KEY", "KAKAO_REST_KEY",
             "NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET",           # .env에 넣는 키 이름 (README '키 준비' 참고)
             "GOOGLE_CLIENT_ID", "KAKAO_LOGIN", "KAKAO_CLIENT_SECRET", "ADMIN_EMAILS")   # 로그인 설정 (backend/app/auth.py)
LLM_TIMEOUT_S = 60       # 한 번 부를 때 기다리는 최대 시간 (SDK 기본은 10분이라, 서버가 멈추면 실행 전체가 멈춘 것처럼 보인다)
LLM_RETRIES = 1          # 실패하면 한 번만 다시
T = TypeVar("T", bound=BaseModel)


def settings() -> dict:
    """환경 변수 > .env 파일 > 기본값.  (.env는 'KEY=VALUE' 줄만 읽는다)"""
    found = dict(DEFAULTS)
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                found[k.strip()] = v.strip().strip('"')
    found.update({k: os.environ[k] for k in (*found, *KEY_NAMES) if k in os.environ})
    return found


def _anthropic(model: str, system: str, user: str, schema: type[T], max_tokens: int) -> T:
    import anthropic                       # LLM 기능을 쓸 때만 필요 (pip install anthropic)
    if "ANTHROPIC_API_KEY" not in os.environ and (key := settings().get("ANTHROPIC_API_KEY")):
        os.environ["ANTHROPIC_API_KEY"] = key
    response = anthropic.Anthropic(timeout=LLM_TIMEOUT_S, max_retries=LLM_RETRIES).messages.parse(
        model=model, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": user}], output_format=schema,
    )
    return response.parsed_output


PROVIDERS = {"anthropic": _anthropic}   # 이름 → 함수(model, system, user, schema, max_tokens) -> schema 객체


def ask(system: str, user: str, schema: type[T], cache_dir: Path, max_tokens: int = 16000, light: bool = False) -> T:
    """system(역할·규칙) + user(자료) → schema 형식의 답. 제공자·모델·규칙·자료가 모두 같으면 저장된 답을 쓴다.
    light=True면 가벼운 모델(LLM_MODEL_LIGHT)을 쓴다."""
    cfg = settings()
    model = cfg["LLM_MODEL_LIGHT" if light else "LLM_MODEL"]
    key = hashlib.sha256(f"{cfg['LLM_PROVIDER']}|{model}|{system}|{user}".encode()).hexdigest()[:16]
    cache = Path(cache_dir) / f"{key}.json"
    if cache.exists():
        return schema.model_validate_json(cache.read_text(encoding="utf-8"))
    result = PROVIDERS[cfg["LLM_PROVIDER"]](model=model, system=system, user=user, schema=schema, max_tokens=max_tokens)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(result.model_dump_json(indent=1), encoding="utf-8")
    return result
