# docs

코드가 아닌 설명 자료입니다. 지금 구조와 실행 방법은 맨 위 [README.md](../README.md), 실험 기록과 한계는 [ml/REVIEW.md](../ml/REVIEW.md)가 기준입니다.

PDF는 `src/`의 HTML을 고친 뒤 Edge로 다시 만들고, 한 장에 들어가는지 확인합니다.

```
msedge --headless=new --no-pdf-header-footer --print-to-pdf=<저장할 PDF 경로> file:///<HTML 절대 경로>
```

| 파일 | 내용 | 상태 |
|---|---|---|
| `prompts/architecture_graph_prompt.md` | 프로젝트 구조를 방향 그래프와 "파일 지도" 표로 그리게 하는 프롬프트 (다른 Claude에 붙여 넣음) | 11/17 구조 기준 |
| `prompts/dev_guide_prompt.md` | 개발자용 설명서(3장) PDF를 만들게 하는 프롬프트 | 11/16 구조 기준. 이후 `evaluate.py`가 `metrics.py`·`calibration.py`로 나뉘는 등 함수 위치가 바뀌었으니, 쓰기 전에 맨 위 README의 폴더 구조와 맞출 것 |
| `prompts/owner_onepager_prompt.md` | 사장님용 설명서(1장) PDF를 만들게 하는 프롬프트 | 성능은 "예상 범위 안에 들 확률"로 설명 |
| `dev_onepager.pdf`, `src/dev_onepager.html` | 개발자용 한 장 요약: 데이터 흐름, 지켜야 할 규칙, 계약, 성능과 한계, 고칠 곳 | 11/17 구조 기준 |
| `user_onepager.pdf`, `src/user_onepager.html` | 사장님용 한 장 안내: 쓰는 방법, 숫자 읽는 법, 얼마나 맞나(예상 범위 안에 든 비율), 데이터 처리 | 11/17 기준. 실매장 결과가 나오면 '얼마나 맞나'의 수치를 바꿀 것 |
| `LLM_AGENT_CONTEXT.md` | 에이전트 부분을 직접 만들기로 했을 때의 개발 계획 | 11/16 기록용 (지금 구조와 다름) |
