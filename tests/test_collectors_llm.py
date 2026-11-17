"""새얼 수집기의 LLM 호출(Claude로 교체) 테스트: 응답에서 JSON만 꺼내기. 실제 API는 부르지 않는다."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))   # 수집기는 backend/에서 'collectors'로 import
from collectors.llm import parse_json  # noqa: E402


def test_parse_json_handles_fences_and_extra_words():
    assert parse_json('```json\n[{"a": 1}]\n```') == [{"a": 1}]
    assert parse_json('결과입니다: {"x": [1, 2]} 이상입니다.') == {"x": [1, 2]}
    assert parse_json("[]") == []
    with pytest.raises(ValueError):
        parse_json("해당 일정이 없습니다.")


def test_llm_json_uses_cache(tmp_path, monkeypatch):
    """같은 프롬프트는 한 번만 부른다 (학사일정 원문을 매번 다시 읽지 않게)."""
    import collectors.llm as llm
    monkeypatch.setattr(llm, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(llm, "_settings", lambda: ("key", "model"))
    calls = []
    monkeypatch.setattr(llm, "_call_claude", lambda k, m, p: calls.append(p) or '[{"title": "개강"}]')
    assert llm.llm_json("p") == [{"title": "개강"}] and llm.llm_json("p") == [{"title": "개강"}]
    assert calls == ["p"]
