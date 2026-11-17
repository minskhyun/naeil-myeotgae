"""LLM 호출을 한곳에 모아 둔다. 다른 모델로 바꿀 때 이 파일만 고치면 된다.

SDK 대신 REST API 를 직접 부른다. 응답이 없을 때 끝없이 기다리지 않도록 제한 시간을 둔다.
서버가 붐빌 때(429, 500, 503)는 잠시 기다렸다 다시 시도하고, 그래도 안 되면 다음 모델로 넘어간다.
"""
import json
import os
import time

import requests
from dotenv import load_dotenv

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODELS = "gemini-flash-lite-latest,gemini-3.5-flash-lite,gemini-3.1-flash-lite"
TIMEOUT_SECONDS = 120
RETRY_STATUS = {429, 500, 503}
WAITS = [5, 15, 30]  # 재시도 전 대기 시간(초)


def _models():
    """GEMINI_MODEL 을 먼저 쓰고, GEMINI_FALLBACK_MODELS 를 순서대로 예비로 쓴다."""
    first = os.environ.get("GEMINI_MODEL", "")
    rest = os.environ.get("GEMINI_FALLBACK_MODELS", DEFAULT_MODELS)
    names = [first] + rest.split(",")
    seen = []
    for n in names:
        n = n.strip().replace("models/", "")
        if n and n not in seen:
            seen.append(n)
    return seen


def _call(model: str, key: str, prompt: str):
    return requests.post(
        f"{BASE_URL}/models/{model}:generateContent",
        headers={"x-goog-api-key": key},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
        },
        timeout=TIMEOUT_SECONDS,
    )


def llm_json(prompt: str):
    """프롬프트를 보내고 JSON 으로 파싱한 결과를 돌려준다."""
    load_dotenv()
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise SystemExit("backend/.env 에 GEMINI_API_KEY 가 없습니다.")

    last_error = ""
    for model in _models():
        for attempt in range(len(WAITS) + 1):
            try:
                resp = _call(model, key, prompt)
            except requests.Timeout:
                last_error = f"{model}: {TIMEOUT_SECONDS}초 안에 응답 없음"
                print(f"  [retry] {last_error}", flush=True)
                break  # 응답이 없는 모델은 기다리지 말고 다음 모델로
            if resp.status_code == 200:
                parts = resp.json()["candidates"][0]["content"]["parts"]
                text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
                return json.loads(text)
            last_error = f"{model} {resp.status_code}: {resp.text[:200]}"
            if resp.status_code not in RETRY_STATUS:
                break  # 404 같은 오류는 다시 해도 같으니 다음 모델로
            if attempt < len(WAITS):
                print(f"  [retry] {model} {resp.status_code}, {WAITS[attempt]}초 뒤 다시 시도", flush=True)
                time.sleep(WAITS[attempt])
        print(f"  [next] {model} 포기, 다음 모델로", flush=True)
    raise RuntimeError(f"모든 Gemini 모델 실패. 마지막 오류: {last_error}")