# docs

코드가 아닌 설명 자료입니다. 지금 구조와 실행 방법은 맨 위 [README.md](../README.md), 실험 기록과 한계는 [ml/REVIEW.md](../ml/REVIEW.md)가 기준입니다.

| 파일 | 내용 | 상태 |
|---|---|---|
| `prompts/architecture_graph_prompt.md` | 프로젝트 구조를 방향 그래프와 "파일 지도" 표로 그리게 하는 프롬프트 (다른 Claude에 붙여 넣음) | 11/17 구조 기준 |
| `prompts/dev_guide_prompt.md` | 개발자용 설명서(3장) PDF를 만들게 하는 프롬프트 | 11/16 구조 기준. 이후 `evaluate.py`가 `metrics.py`·`calibration.py`로 나뉘는 등 함수 위치가 바뀌었으니, 쓰기 전에 맨 위 README의 폴더 구조와 맞출 것 |
| `prompts/owner_onepager_prompt.md` | 사장님용 설명서(1장) PDF를 만들게 하는 프롬프트 | 성능은 "예상 범위 안에 들 확률"로 설명 |
| `dev_onepager.pdf`, `src/dev_onepager.html` | 개발자용 한 장 요약 | **11/16 초안.** 수집기 통합 전 구조라 주변 정보 수집 부분이 지금과 다름 |
| `user_onepager.pdf`, `src/user_onepager.html` | 사장님용 한 장 안내 | **11/16 초안.** 성능을 "약 27%"로 적은 옛 표현. 새로 만들 때는 위 프롬프트 사용 |
| `LLM_AGENT_CONTEXT.md` | 에이전트 부분을 직접 만들기로 했을 때의 개발 계획 | 11/16 기록용 (지금 구조와 다름) |
