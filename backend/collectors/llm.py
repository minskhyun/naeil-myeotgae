"""LLM 호출을 한곳에 모아 둔다. 다른 모델로 바꿀 때 이 파일만 고치면 된다.

11/17: Gemini → Claude. 키와 모델은 프로젝트 맨 위 .env 하나로 관리한다 (ml/alerts.py의 LLM 경고와 같은 설정).
    ANTHROPIC_API_KEY=...        (필수)
    LLM_MODEL=claude-opus-5-5    (선택, 기본값)

- Anthropic 공식 SDK를 쓴다. 서버가 붐빌 때(429, 5xx)는 SDK가 알아서 기다렸다 다시 시도한다 (MAX_RETRIES).
- 학사일정 페이지처럼 입력이 길 수 있어 스트리밍으로 받는다 (긴 응답에서 연결이 끊기지 않게).
- 프롬프트는 JSON만 출력하라고 하고, 응답에서 JSON 부분만 꺼내 파싱한다. 형식이 틀리면 ValueError
  → 부르는 쪽(agent.py)이 규칙으로 대신한다.
"""
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv

MAX_RETRIES = 4
MAX_TOKENS = 32000
SYSTEM = "요청한 형식의 JSON만 출력한다. 설명, 코드 블록 표시(```), 앞뒤 문장을 붙이지 않는다."


ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"   # 프로젝트 맨 위 .env (수집기는 backend/에서 실행돼도)
DEFAULT_MODEL = "claude-opus-5-5"


def _settings() -> tuple[str, str]:
    """(API 키, 모델). ml.alerts.settings와 같은 규칙: 환경 변수 > 맨 위 .env > 기본값."""
    load_dotenv(ROOT_ENV)                              # 이미 있는 환경 변수는 덮어쓰지 않는다
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise SystemExit(f"{ROOT_ENV} 에 ANTHROPIC_API_KEY 가 없습니다.")
    return key, os.environ.get("LLM_MODEL") or DEFAULT_MODEL


def model_name() -> str:
    """정보원 계획 파일에 '어떤 모델이 골랐는지' 남길 때 쓴다."""
    return _settings()[1]


def parse_json(text: str):
    """응답 글자 → JSON. 코드 블록 표시나 앞뒤 문장이 섞여 있어도 첫 '[' 또는 '{'부터 짝이 맞는 끝까지 읽는다."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start = min((i for i in (text.find("["), text.find("{")) if i >= 0), default=-1)
    if start < 0:
        raise ValueError(f"JSON이 없는 응답: {text[:120]!r}")
    obj, _ = json.JSONDecoder().raw_decode(text[start:])
    return obj


CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "llm_cache"   # 커밋 안 함 (.gitignore의 llm_cache/)


def llm_json(prompt: str):
    """프롬프트를 보내고 JSON 으로 파싱한 결과를 돌려준다.
    같은 모델·같은 프롬프트는 다시 부르지 않는다 (학사일정 원문 8개를 매번 다시 읽으면 비용·시간이 크다)."""
    import hashlib
    key, model = _settings()
    cache = CACHE_DIR / (hashlib.sha256(f"{model}|{SYSTEM}|{prompt}".encode()).hexdigest()[:20] + ".txt")
    if cache.exists():
        return parse_json(cache.read_text(encoding="utf-8"))
    text = _call_claude(key, model, prompt)
    result = parse_json(text)                       # 형식이 틀린 응답은 저장하지 않는다
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(text, encoding="utf-8")
    return result


def _call_claude(key: str, model: str, prompt: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=key, max_retries=MAX_RETRIES)
    with client.messages.stream(model=model, max_tokens=MAX_TOKENS, thinking={"type": "adaptive"}, system=SYSTEM,
                                messages=[{"role": "user", "content": prompt}]) as stream:
        message = stream.get_final_message()
    if message.stop_reason == "max_tokens":
        raise ValueError("응답이 너무 길어 중간에 끊겼습니다 (MAX_TOKENS를 늘리거나 입력을 줄이세요).")
    return "".join(b.text for b in message.content if b.type == "text")
