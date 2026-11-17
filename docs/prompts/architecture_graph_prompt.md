"내일몇개" 프로젝트의 구조를 **방향 그래프**로 그려 주세요. 처음 이 코드를 보는 개발자가 그림 두 장만 보고 "무엇이 무엇을 부르고, 어떤 파일을 읽고 쓰는지"를 파악할 수 있어야 합니다.

<결과물>
1. Mermaid 코드 두 개 (각각 ```mermaid 블록)
   - 그림 A "전체 흐름": 묶음(레이어) 단위, 노드 15개 안팎
   - 그림 B "모듈 상세": 파일 단위, 노드 45개 이하
2. "파일 지도" 표: 아래 <전체 파일 목록>의 **모든 파일·폴더**를 한 줄씩. 칸 = 위치 / 묶음(그림과 같은 색) / 역할(쉬운 한국어 한 줄) / 그림 B에 있음(○·×) / 저장소에 커밋됨(○·×)
3. 그림 두 개와 표를 함께 보여 주는 HTML 파일 하나
   - Mermaid는 `https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js` 하나만 불러옵니다.
   - 그림마다 제목, 한 줄 설명, 범례(노드 모양·선 종류·색의 뜻)를 붙입니다.
   - 표는 묶음별로 나누고, 위쪽에 묶음 이름으로 바로 가는 목차를 둡니다.
</결과물>

<프로젝트 사실>
아래가 실제 구조입니다. 여기에 없는 파일·함수·연결을 지어내지 마세요. 그림을 단순하게 만들려고 노드를 합치는 것은 괜찮지만, 없는 화살표를 만들면 안 됩니다.

## 한 줄 소개
카페·베이커리 POS 판매 기록 + 매장 주변 정보(날씨·행사·학사일정·뉴스·유행) → 내일 메뉴별 판매량 범위와 준비량. LLM(Claude)은 판매량 숫자를 만들지 않고, 정보를 찾고 정리하고 주의 문장만 씁니다.

## 진입점 (실행이 시작되는 곳)
- `run.py`: 한 매장 전체 실행. 단계 = ingest → evaluate → predict
- `backend/app/main.py` (FastAPI 웹 API): 업로드를 받으면 `run.py`를 별도 프로세스로 실행, 준비 방식을 바꾸면 `run.py --from-step predict` 실행. 결과 JSON을 화면에 돌려줌
- `frontend/src/` (React 화면): `main.tsx`(시작) → `App.tsx` → `ForecastView.tsx`(내일 준비표), `BacktestView.tsx`(얼마나 맞나), `UploadView.tsx`(데이터 올리기). 모두 `api.ts`로 `/api/...` 호출, 실행 상태는 `useJob.ts`가 1.5초마다 확인, 날짜·퍼센트 표시는 `format.ts`
- `frontend/vite.config.ts`: 개발 중 화면(5173)의 `/api` 요청을 백엔드(8000)로 넘김. 배포 때는 백엔드가 빌드된 화면을 직접 제공
- `frontend/public/sample-news/*.html`: 시연용 가상 기사 4개. 화면의 '원문' 링크가 여기로 감

## run.py 단계별 흐름
### ingest
- `ml/ingest.py`: POS 엑셀·CSV → `data/artifacts/{매장}/sales_clean.csv` (머리글 찾기, 메뉴명 정리, 0개 판매 채우기, 휴무 제외, 품절 추정)
- 매장 설정 `data/artifacts/{매장}/store.json` 만들기·고치기. 주소 → 좌표는 `agent/geocode.py` (카카오 → 안 되면 OpenStreetMap)
- 주변 정보 자동 수집: `agent/collect.py`의 `collect_all` (정보원 목록 `SOURCES`를 차례로 실행: public_data → special_days → event_posts → menu_trend). 아래 1~3은 public_data가 `agent/collectors_bridge.py`를 통해 하는 일
  1. 매장별 수집 폴더 `data/artifacts/{매장}/collectors/`에 `stores.json`(이 매장 하나) 쓰기
  2. 공공 데이터 수집기 실행: `python -m collectors.run_all` (backend/에서, 별도 프로세스, 환경 변수 `COLLECTORS_WORK_DIR`=위 폴더 → 결과가 모두 그 폴더에 생김). `run_all.py`가 순서대로 부름:
     - `kakao.py` → 카카오 로컬 API → `{매장}_nearby.json` (주변 시설)
     - `agent.py` (정보원 선택 에이전트) → `llm.py`(Claude) → `{매장}_sources.json` (쓸 학교·행사 반경과 이유)
     - `build_external_daily.py` → `weather.py`(기상청 ASOS 관측) + `holidays.py`(한국천문연구원 특일) → `external_daily.csv`
     - `forecast.py` → 기상청 단기예보 → `external_daily.csv`에 내일·모레 추가
     - `academic.py` → 대학 학사일정 페이지(원문은 `backend/data/raw/academic/`) → `llm.py`(Claude) 추출 → `events.json` + csv 반영
     - `seoul_events.py` → 서울 열린데이터 문화행사 API → `events.json` + csv 반영
     - 공통: `store.py`(매장·계획 읽기, 결과 파일 위치), `llm.py`(수집기의 LLM 호출, Claude, 캐시)
  3. 변환: `external_daily.csv` + `events.json` + `{매장}_sources.json` → SignalRow·CollectionItem (공개 시각 붙임)
  4. 그 밖의 정보원:
     - `agent/special_days.py` → 기념일 신호
     - `agent/naver.py` → NAVER API HUB 뉴스·블로그 검색 → 글 주소 목록
     - `agent/events.py` → 글(사람이 적은 `data/raw/{매장}_event_sources.txt` + 네이버 검색 글)을 읽고 LLM(Claude)이 날짜·장소 추출 → `agent/geocode.py`로 거리 확인 → 근처 행사 신호 + 원문
     - `agent/naver.py` → NAVER API HUB 검색어 트렌드(메뉴 검색량) → 메뉴별 유행 신호(`trend_level`, 모델 입력 후보) + '검색량 변화' 원문
  5. 결과 → `data/artifacts/{매장}/signals.csv` (신호), `collection.json` (AI 주의 안내용 원문)
### evaluate
- `ml/evaluate.py` (`run_backtest`) → `ml/features.py`(입력 표 `build_frame`, 시점 규칙) → `ml/models.py`(M0 기준선, CatBoost 다중 분위) → 시간순 교차검증 → 신호 조합 선택(`choose_signals`·`pick_combo`) → 범위 보정(`ml/calibration.py`) → 최종 테스트 1회 → `data/artifacts/{매장}/backtest.json`. 점수 계산은 `ml/metrics.py`
### predict
- `ml/predict.py` (`predict_from_backtest`) → `features.py`·`models.py`로 다시 학습 → 내일 예측, 근거 문장, 준비량 → `ml/alerts.py` (`collection.json` + Claude → AI 주의 안내, 인용문 원문 대조) → `data/artifacts/{매장}/forecast.json`
- `ml/llm.py`: `.env` 설정 읽기(`settings`) + Claude 호출·응답 저장(`ask`). `ml/alerts.py`와 `agent/events.py`가 LLM을 부를 때, `agent/geocode.py`·`agent/naver.py`가 키를 읽을 때 씀

## 공통·기타
- `contracts/schemas.py`: 팀 공통 데이터 형식 (StoreConfig = store.json, SalesRow, SignalRow, CollectionItem, Forecast, BacktestResult, Warning). ml·agent·backend가 모두 씀 → 그림 B에서는 노드 하나로 두고 '형식 사용' 점선만 몇 개 그리세요 (모든 파일에 연결하면 복잡해짐)
- `ml/calendar_kr.py`: 공휴일 목록 (`features.py`가 씀), `ml/sample_data.py`: 가상 매장 생성 → `data/sample/sinchon-a/`, `ml/paths.py`: 폴더 위치(ROOT·SAMPLE·RAW·ARTIFACTS, 여러 파일이 가져다 씀 → 그림에는 그리지 않고 표에만)
- 시연 배포: `Dockerfile`이 화면을 빌드해 `backend/app/main.py`가 함께 제공. `DEMO_MODE=1`이면 보기 전용, 결과는 `backend/demo_data/`. `render.yaml`로 Render에 배포
- 키: 맨 위 `.env` 하나 (Claude, 공공데이터포털, 서울 열린데이터, 카카오, 네이버 API HUB)

## 외부 서비스 (그림에서 따로 묶기)
- Anthropic Claude: 4곳에서 씀 → `collectors/agent.py`(정보원 선택), `collectors/academic.py`(학사일정 추출), `agent/events.py`(행사 글 추출), `ml/alerts.py`(AI 주의 안내). 앞의 둘은 `collectors/llm.py`, 뒤의 둘은 `ml/llm.py`를 거쳐 부름
- 기상청 ASOS 관측·단기예보, 한국천문연구원 특일 (공공데이터포털)
- 서울 열린데이터광장 문화행사
- 카카오 로컬 (주변 시설, 장소 → 좌표)
- NAVER API HUB (뉴스·블로그 검색, 검색어 트렌드)
- OpenStreetMap Nominatim (카카오로 못 찾은 주소)
</프로젝트 사실>

<전체 파일 목록>
"파일 지도" 표에 아래를 빠짐없이 넣습니다. 폴더 안 파일이 많은 곳(학사일정 원문, 테스트)은 폴더 한 줄로 적고 파일 수를 씁니다.
(커밋 안 함) 표시는 .gitignore로 저장소에 올리지 않는 파일입니다.

맨 위
- run.py: 한 매장 전체 실행
- requirements.txt: 파이썬 패키지 목록 / pytest.ini: 테스트 설정
- .env (커밋 안 함): 모든 API 키
- .gitignore: 올리지 않을 파일 규칙 / Dockerfile·.dockerignore·render.yaml: 시연 사이트 배포(이미지에서 키·실데이터 제외)
- README.md: 서비스 소개·실행 방법·폴더 구조 / PROJECT_CONTEXT.md: 기획·팀 맥락
- docs/: 설명서 PDF(dev_onepager.pdf, user_onepager.pdf)와 그 원본(src/), 다른 Claude용 프롬프트(prompts/), 11/16 에이전트 개발 계획 기록(LLM_AGENT_CONTEXT.md)

contracts/
- schemas.py: 팀 공통 데이터 형식 / __init__.py
- examples/: backtest.json·forecast.json·sales.csv·signals.csv (화면·백엔드 개발용 예시 파일)

ml/
- ingest.py, features.py, models.py, metrics.py, calibration.py, evaluate.py, predict.py, alerts.py, llm.py (위 흐름 참고)
- calendar_kr.py: 공휴일 목록 / sample_data.py: 가상 매장 만들기 / paths.py: 폴더 위치 / __init__.py
- TASKS.md: 예측 엔진 개발 명세 / REVIEW.md: 판단·확인 목록, 진행 기록

agent/
- collect.py: 주변 정보 수집의 입구(정보원 목록 SOURCES) / collectors_bridge.py: 공공 데이터 수집기 실행 + 결과 변환 / events.py: 행사 글 LLM 추출 / naver.py: 네이버 검색·검색어 트렌드
- geocode.py: 주소·장소 → 좌표 / special_days.py: 기념일 / __init__.py

backend/
- app/main.py: 웹 API / app/__init__.py, __init__.py
- collectors/: run_all.py, kakao.py, agent.py, build_external_daily.py, weather.py, holidays.py, forecast.py, academic.py, seoul_events.py, store.py, llm.py (위 흐름 참고)
- collectors/academic_sources.json: 학교·학기별 학사일정 페이지 주소와 날짜 범위 (academic.py가 읽음)
- collectors/stores.json: 수집기만 따로 실행할 때의 매장 목록 (신촌 예시 매장)
- data/external_daily.csv, data/events.json, data/stores/shinchon-cafe-a_nearby.json·_sources.json: 수집기만 따로 실행한 신촌 예시 결과 (실제 매장 결과는 data/artifacts/{매장}/collectors/에 생김)
- data/raw/academic/: 학사일정 원문 텍스트 8개 / data/raw/seoul_culture/ (커밋 안 함): 서울 행사 원본 / data/llm_cache/ (커밋 안 함): 수집기 LLM 응답 저장
- demo_data/sinchon-a/·fr-bakery/: 시연 사이트용 미리 계산한 결과 (forecast.json, backtest.json, store.json)

frontend/
- index.html: 화면 시작 페이지(제목·글꼴) / vite.config.ts: /api 프록시
- package.json·package-lock.json: 화면 패키지 / tsconfig.json·tsconfig.app.json·tsconfig.node.json: 타입 검사 설정 / eslint.config.js: 코드 검사 / .gitignore
- src/: main.tsx, App.tsx, api.ts(타입·요청), useJob.ts, format.ts(이름표·날짜·퍼센트), ForecastView.tsx, BacktestView.tsx, UploadView.tsx, index.css(색·글꼴)
- public/favicon.svg: 아이콘 / public/sample-news/: 시연용 가상 기사 4개

data/
- sample/sinchon-a/: 가상 매장 1년치 — sales.csv(판매), pos_raw.csv(POS 원본 모양), signals.csv(신호), store.json(설정), truth.json(심어 둔 정답 효과), demand_true.csv(품절 전 실제 수요), collection.json(시험용 가상 기사)
- raw/ (커밋 안 함): 실매장 POS 파일, {매장}_event_sources.txt(사람이 모은 행사 글 주소), geocode_cache.json(주소 → 좌표 저장), llm_cache_events/(행사 글 LLM 응답 저장), uploads/(웹으로 올린 파일)
- artifacts/{매장}/ (커밋 안 함): store.json, sales_clean.csv, ingest_log.json(읽기 기록), menu_merge_candidates.json(메뉴명 통일 후보), collectors/(수집기 결과: stores.json, external_daily.csv, events.json, {매장}_nearby.json, {매장}_sources.json), signals.csv, collection.json, backtest.json, forecast.json, llm_cache/(AI 주의 안내 응답 저장)

tests/
- test_*.py 16개 + fixtures/(시험용 POS 파일): 모듈마다 자동 테스트. 그림에는 그리지 않고 표에만 한 줄
</전체 파일 목록>

<그리는 규칙>
- 방향: 왼쪽 → 오른쪽 (`flowchart LR`). 입력(POS 파일·주소) → 수집 → 예측 엔진 → 결과 파일 → 웹 화면 순으로 읽히게.
- 묶음(subgraph)과 색: 묶음마다 색 하나를 정하고 두 그림에서 같은 색을 씁니다.
  입력 / 진입점(run.py·웹 API) / 공공 데이터 수집(backend/collectors) / 연결·그 밖의 정보원(agent) / 예측 엔진(ml) / 결과 파일(data/artifacts) / 웹 화면(frontend) / 외부 서비스 / 공통 형식(contracts)
- 노드 모양:
  - 코드 파일 = 사각형
  - 데이터 파일 = 원통 (`[(…)]`)
  - 외부 서비스 = 육각형 (`{{…}}`)
  - 사람·화면 = 둥근 사각형
- 선 종류 (범례에 꼭 표시):
  - 실선 화살표 = 호출·실행
  - 점선 화살표 = 파일 읽기·쓰기 (화살표 방향 = 데이터가 흐르는 방향)
  - 굵은 선 = 외부 서비스 호출
- Claude를 쓰는 노드 4개는 이름 뒤에 "★Claude"를 붙여 한눈에 보이게 합니다.
- 노드 이름: 첫 줄 = 파일 이름, 둘째 줄 = 쉬운 한국어 역할 (예: `ml/evaluate.py<br/>검증·신호 선택`). 한 노드 두 줄 이하.
- 선 위 글자는 2~6자로 짧게 (예: "실행", "읽기", "쓰기", "검색"). 모든 선에 글자를 붙이지 말고, 헷갈리는 선에만.
- 그림 B에서 노드가 45개를 넘으면 수집기 안의 `weather.py`·`holidays.py`·`store.py`처럼 작은 파일을 부모 노드에 합치고, 합쳤다는 사실을 노드 이름에 적습니다.
- 테스트(`tests/`)는 그리지 않습니다.
</그리는 규칙>

<마무리 확인>
답을 주기 전에 확인하고 고치세요.
1. <프로젝트 사실>에 없는 노드·화살표가 없는가
2. Mermaid 문법 오류가 없는가 (특히 괄호·따옴표가 든 이름은 따옴표로 감쌌는가)
3. "파일 지도" 표에 <전체 파일 목록>의 항목이 하나도 빠지지 않았는가
4. 이 질문 세 개에 그림만 보고 답할 수 있는가:
   - "POS 파일을 올리면 forecast.json까지 어떤 순서로 가나?"
   - "Claude는 어디어디서 쓰나?"
   - "네이버 뉴스에서 찾은 행사는 어느 파일을 거쳐 화면의 주의 안내가 되나?"
확인 결과를 마지막에 네 줄 이내로 적어 주세요.
</마무리 확인>
