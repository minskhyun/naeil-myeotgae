# 내일몇개 (naeil-myeotgae)

> 매장 POS 판매 기록과 매장 주변 정보(날씨·행사·학사일정·뉴스·유행)를 함께 보고, **메뉴별 내일 판매량 범위와 준비량**을 알려 주는 카페·베이커리용 AI 수요 예측 서비스

2026 연세 캠퍼스타운 AI 스타트업 해커톤 본선 프로토타입 (팀 PREDICTOR)

## 문제

소규모 카페·베이커리 사장님은 "내일 몇 개 만들까?"를 대부분 감으로 정합니다. 적게 만들면 품절, 많이 만들면 폐기가 생깁니다. 판매량은 요일뿐 아니라 날씨, 근처 행사, 대학 학사일정, 메뉴 유행에 따라 흔들리고, 어떤 요인이 중요한지는 매장마다 다릅니다.

## 해결 방법

사장님은 **POS 파일과 매장 주소만** 올립니다. 나머지는 자동입니다.

```
POS 파일 + 매장 주소
   │
   ├─ 1. 판매 기록 정리      메뉴명 정리, 휴무·품절 처리
   ├─ 2. 주변 정보 수집      주소 → 주변 시설 → AI가 이 매장에 맞는 정보원 선택
   │                         → 날씨·공휴일·학사일정·문화행사·뉴스·블로그·메뉴 검색량
   ├─ 3. 검증                과거 기록으로 "어떤 정보가 실제로 오차를 줄이는지" 확인,
   │                         도움이 되는 정보만 채택
   ├─ 4. 내일 예측           메뉴별 판매량 범위, 근거, 준비량 (폐기 줄이기 / 균형 / 품절 줄이기)
   └─ 5. AI 주의 안내        모델이 모르는 특별한 상황(새 팝업, 유행 급변 등)을 원문 인용과 함께 알림
   │
웹 화면: 내일 준비표 · 얼마나 맞나 · 데이터 올리기
```

### AI를 쓰는 곳

판매량 숫자는 판매 기록으로 학습한 예측 모델(CatBoost)이 만듭니다. **LLM(Claude)은 숫자를 만들거나 고치지 않고**, 정보를 찾고 정리하고 주의 문장만 씁니다.

| 하는 일 | 파일 | 코드가 다시 확인하는 것 |
|---|---|---|
| 이 매장에 쓸 정보원 고르기 (어느 학교, 행사 반경) | `backend/collectors/agent.py` | 주변 시설 목록에 실제로 있는 이름만 인정, 반경 300~2000m |
| 학사일정 페이지에서 일정 뽑기 | `backend/collectors/academic.py` | 제목이 원문에 있는지, 날짜가 학기 범위 안인지 |
| 뉴스·블로그·공지 글에서 행사 날짜·장소 뽑기 | `agent/events.py` | 근거 문장이 원문에 그대로 있는지, 매장에서 1km 안인지 |
| 내일의 특별한 상황 알리기 (AI 주의 안내) | `ml/alerts.py` | 인용문이 원문에 그대로 있는지, 예측 시각 뒤에 공개된 글은 제외 |

같은 입력은 응답을 저장해 두고 다시 부르지 않습니다. 시연 때 결과가 바뀌지 않고 비용도 한 번만 듭니다.

### 모델 비교

| 모델 | 구성 |
|---|---|
| M0 | 지난주 같은 요일 판매량 (기준선) |
| M1 | 판매 이력 + 요일·공휴일 (CatBoost) |
| M2 | M1 + 날씨 |
| M3 | M2 + 학사일정·행사·기념일 |

- 외부 정보는 묶음(날씨 / 학사일정·행사 / 기념일)의 **모든 조합**을 같은 검증 구간에서 비교합니다. M1보다 전체 오차(WAPE)가 3% 이상 줄고 검증 구간 과반에서 나아진 조합만 채택하고, 조합 안에서 빼도 나빠지지 않는 묶음은 뺍니다. 개선이 없으면 M1을 그대로 씁니다.
- 예측은 범위(p10~p90)로 냅니다. 준비량은 폐기 줄이기 p40, 균형 p50, 품절 줄이기 p80입니다.
- **시점 규칙:** D일 예측은 D−1일 영업 종료 시각에 낸 것으로 봅니다. 그 시각 뒤에 공개된 날씨 예보·뉴스·공지는 학습과 검증에 쓰지 않습니다.

## 검증 결과

시간순으로 나눈 마지막 28일(최종 테스트, 한 번만 평가)의 결과입니다.

| 데이터 | 선택된 모델 | 예상 범위 안에 든 비율 | 오차 WAPE (기준선 M0) |
|---|---|---|---|
| 가상 매장 1년 (효과를 심어 만든 신촌 카페) | M3 (날씨 + 학사일정·행사) | 75% | 0.191 (0.297) |
| 프랑스 베이커리 600일 (Kaggle 공개 실데이터) | M1 (외부 정보 없음) | 76% | 0.303 (0.412) |

- "예상 범위 안에 든 비율"은 실제 판매량이 p10~p90 범위 안에 들어온 비율입니다 (목표 80%).
- 가상 매장은 우리가 만든 효과가 들어 있어 실제 매장보다 쉽습니다. 프랑스 베이커리의 테스트 구간은 개선 과정에서 한 번 본 구간이라 완전히 독립된 확인은 아닙니다.
- 협력 매장 실데이터 결과는 확정되면 추가합니다. 자세한 실험 기록과 한계는 [ml/REVIEW.md](ml/REVIEW.md)에 있습니다.

## 실행 방법

Python 3.11 이상과 Node.js 22(화면)가 필요합니다. 명령은 모두 **프로젝트 맨 위 폴더**에서 실행합니다.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 1. 가상 매장으로 끝까지 돌려 보기 (키 없이 가능)

```bash
python run.py --store sinchon-a --demo
```

`data/artifacts/sinchon-a/`에 `backtest.json`(검증 결과)과 `forecast.json`(내일 예측)이 생깁니다. 1~2분 걸립니다.

### 2. 웹 화면

터미널 두 개를 씁니다.

```bash
# 터미널 1: 백엔드 (http://localhost:8000/docs 에서 API 확인)
uvicorn backend.app.main:app --port 8000

# 터미널 2: 화면 (http://localhost:5173)
cd frontend
npm install
npm run dev
```

### 3. 실제 매장 데이터

웹 화면의 '데이터 올리기'에서 매장 주소와 POS 파일(토스·OKPOS 엑셀 또는 CSV)을 올리거나, 명령줄에서 실행합니다.

```bash
python run.py --store seongsu-a --pos data/raw/pos.xlsx --address "서울 성동구 서울숲2길 12-7"
python run.py --store seongsu-a --from-step predict      # 예측만 다시
```

주변 정보를 자동으로 모으려면 아래 키가 필요합니다. 키가 없는 정보원은 건너뛰고 나머지로 계속합니다.

### 키 준비

프로젝트 맨 위에 `.env` 파일을 만듭니다. 이 파일은 저장소에 올리지 않습니다.

```
ANTHROPIC_API_KEY=Claude API 키
DATA_GO_KR_KEY=공공데이터포털 인증키 (Decoding)
SEOUL_DATA_KEY=서울 열린데이터광장 인증키
KAKAO_REST_KEY=카카오 디벨로퍼스 REST API 키 (카카오맵 사용 설정)
NAVER_CLIENT_ID=NAVER API HUB Client ID
NAVER_CLIENT_SECRET=NAVER API HUB Client Secret
LLM_MODEL=claude-opus-5-5          # 선택 (기본값)
```

| 키 | 쓰는 곳 | 신청할 것 |
|---|---|---|
| `ANTHROPIC_API_KEY` | 위 표의 LLM 네 곳 | Anthropic Console |
| `DATA_GO_KR_KEY` | 날씨, 공휴일 | 공공데이터포털에서 '기상청_지상(종관, ASOS) 일자료 조회서비스', '기상청_단기예보 조회서비스', '한국천문연구원_특일 정보' 활용신청 |
| `SEOUL_DATA_KEY` | 서울 문화행사 | 서울 열린데이터광장 '서울시 문화행사 정보' |
| `KAKAO_REST_KEY` | 주변 시설, 주소·장소 → 좌표 | 카카오 디벨로퍼스 (없으면 좌표는 OpenStreetMap으로 찾음) |
| `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` | 뉴스·블로그 검색, 검색어 트렌드 | NAVER API HUB (2026-07-31부터 신규 키는 여기서만 발급) |

### 테스트

```bash
pytest                              # 인터넷·API 키 없이 2분 안에 끝남
cd frontend && npm run build && npm run lint
```

## 폴더 구조

```
.
├── run.py                  한 매장 전체 실행: ingest → evaluate → predict (웹도 이 파일을 실행)
├── contracts/              팀 공통 데이터 형식 (schemas.py)과 예시 파일
├── ml/                     예측 엔진
│   ├── ingest.py           POS 파일 → 판매 기록
│   ├── features.py         모델 입력 표 (시점 규칙, 신호 이름 목록)
│   ├── models.py           M0 기준선, CatBoost 분위 예측
│   ├── metrics.py          지표 (WAPE, 범위 적중 등)
│   ├── calibration.py      예측 범위 보정
│   ├── evaluate.py         시간순 검증, 신호 조합 선택 → backtest.json
│   ├── predict.py          내일 예측·근거·준비량 → forecast.json
│   ├── alerts.py           AI 주의 안내
│   ├── llm.py              .env 설정 읽기, Claude 호출과 응답 저장
│   ├── paths.py            폴더 위치
│   ├── calendar_kr.py      공휴일 목록
│   ├── sample_data.py      가상 매장 만들기
│   └── REVIEW.md           판단 기록, 알려진 한계, 코드 지도
├── agent/                  주변 정보 수집
│   ├── collect.py          입구: 정보원 목록(SOURCES)을 차례로 실행해 합침
│   ├── collectors_bridge.py   공공 데이터 수집기 실행 + 결과를 예측 엔진 입력으로 변환
│   ├── events.py           뉴스·블로그·공지 글에서 행사 추출
│   ├── naver.py            네이버 뉴스·블로그 검색, 메뉴 검색량
│   ├── geocode.py          주소·장소 → 좌표
│   └── special_days.py     기념일
├── backend/
│   ├── app/main.py         웹 API (FastAPI)
│   ├── collectors/         공공 데이터 수집기와 정보원 선택 에이전트
│   ├── data/               수집기를 따로 실행한 예시 결과(신촌), 학사일정 원문
│   └── demo_data/          공개 시연 사이트용 결과 (가상 매장, 공개 데이터)
├── frontend/               웹 화면 (React, Vite, Tailwind)
├── data/sample/            가상 매장 1년치
├── docs/                   설명서와 문서 작성용 프롬프트
└── tests/                  자동 테스트
```

커밋하지 않는 것: `.env`, `data/raw/`(실제 POS 파일), `data/artifacts/`(매장별 결과)

매장별 결과 폴더 `data/artifacts/{매장}/`의 내용:

| 파일 | 내용 |
|---|---|
| `store.json` | 매장 설정 (주소·좌표, 영업 종료 시각, 준비 방식) |
| `sales_clean.csv` | 정리된 판매 기록 (date, store_id, menu, qty, sold_out) |
| `collectors/` | 수집기 결과: 주변 시설, 정보원 계획과 그 이유, 날씨·행사 원본 |
| `signals.csv` | 모델에 넣는 외부 신호 (날짜, 신호 이름, 값, 출처, 공개 시각) |
| `collection.json` | AI 주의 안내에 쓰는 행사·뉴스 원문 |
| `backtest.json` | 모델 비교와 신호 채택 결과 |
| `forecast.json` | 메뉴별 내일 예측, 근거, 준비량, AI 주의 안내 |

형식은 모두 [contracts/schemas.py](contracts/schemas.py)에 정의되어 있습니다.

### 고칠 때 볼 곳

| 하고 싶은 일 | 고칠 곳 |
|---|---|
| 새 POS 형식 받기 | `ml/ingest.py`의 `COLUMN_MAP`에 열 이름 추가 |
| 새 정보원 추가 | `agent/collect.py`에 함수 하나 + `SOURCES`에 한 줄 |
| 새 신호를 모델에 넣기 | `ml/features.py`의 `SIGNAL_GROUPS`에 이름 추가 (화면 이름은 `frontend/src/format.ts`) |
| 신호 채택 기준 바꾸기 | `ml/evaluate.py`의 `MIN_GAIN_PCT`, `beats` |
| 준비 방식·근거 문장 바꾸기 | `ml/predict.py`의 `PREP_MODES`, `reason_text` |
| AI 주의 안내의 규칙 바꾸기 | `ml/alerts.py`의 `SYSTEM` |
| 매장 설정 칸 추가 | `contracts/schemas.py`의 `StoreConfig` |
| LLM 모델·제공자 바꾸기 | `.env`의 `LLM_MODEL`, `ml/llm.py`의 `PROVIDERS` |

## 공공 데이터 수집기 (backend/collectors)

`run.py`가 자동으로 실행하지만, 수집기만 따로 돌릴 수도 있습니다. 매장 정보는 `backend/collectors/stores.json`에 적습니다.

```bash
cd backend
python -m collectors.run_all                  # 2025-11-01 ~ 어제
python -m collectors.run_all --replan         # 매장 주소를 바꿨을 때: 주변 시설과 정보원 선택부터 다시
python -m collectors.run_all --refresh-events # 서울시 행사 목록 새로 받기
```

| 순서 | 모듈 | 하는 일 |
|---|---|---|
| 1 | `kakao` | 매장 좌표와 주변 시설(학교, 문화시설, 관광명소, 지하철역, 공연장, 경기장) 조회 |
| 2 | `agent` | 주변 시설을 보고 LLM이 이 매장에 쓸 학교와 행사 반경을 선택 |
| 3 | `build_external_daily` | 날짜 효과, 공휴일, 관측 날씨로 CSV 새로 만들기 |
| 4 | `forecast` | 단기예보로 내일·모레 날씨 추가 |
| 5 | `academic` | 학사일정 추출, 선택된 학교만 CSV에 반영 |
| 6 | `seoul_events` | 반경 안 문화행사를 CSV에 반영 |

1, 2단계는 결과 파일이 이미 있으면 건너뜁니다. 3단계가 `external_daily.csv`를 새로 쓰므로 단계를 따로 실행할 때도 이 순서를 지켜야 합니다.

결과 파일 위치:

- 따로 실행할 때: `backend/data/external_daily.csv`, `backend/data/events.json`, `backend/data/stores/{store_id}_nearby.json`·`_sources.json`
- `run.py`가 실행할 때: 위 파일이 모두 `data/artifacts/{매장}/collectors/`에 생깁니다 (환경 변수 `COLLECTORS_WORK_DIR`). 실제 매장 결과가 저장소의 예시 파일을 덮어쓰지 않고 매장끼리도 섞이지 않습니다.

### 정보원 선택 에이전트

`agent`는 매장 주변 시설 목록을 LLM에 보여 주고 "이 매장 판매량에 영향을 줄 정보원"을 고르게 합니다. 결과는 코드가 다시 검증합니다.

- 학교는 수집기가 있는 학교만, 주변 시설 목록에 실제로 있는 이름을 근거로 댄 경우만, 3km 이내만 인정합니다.
- 행사 반경은 300~2000m로 제한합니다.
- 지금은 수집할 수 없지만 중요해 보이는 정보원(다른 대학, 경기장 일정 등)은 `candidates`에 남겨 다음 수집기 후보로 씁니다.
- LLM 호출이 실패하면 거리 규칙(2km 안 캠퍼스, 반경 1000m)으로 대신 정합니다. `python -m collectors.agent --rule`로 직접 쓸 수도 있습니다.

결과는 `{store_id}_sources.json`에 근거, 이유, 검증 메모와 함께 저장됩니다.

학사일정 원문은 `backend/data/raw/academic/{학교}_{학기}.txt`에 저장되고, 파일이 있으면 다시 내려받지 않습니다. 자동으로 못 가져오는 학기는 페이지를 복사해 같은 이름으로 저장하고 `collectors/academic_sources.json`에 학기와 날짜 범위를 추가하면 됩니다.

### external_daily.csv

날짜당 한 줄입니다.

| 컬럼 | 내용 |
|---|---|
| `date` | 날짜 (YYYY-MM-DD) |
| `dow`, `is_weekend` | 요일 (0=월 ~ 6=일), 주말 여부 |
| `is_holiday`, `holiday_name` | 공휴일 여부와 이름 |
| `temp_mean`, `temp_min`, `temp_max` | 일 평균·최저·최고 기온 (℃) |
| `rain_mm` | 일강수량 (mm) |
| `weather_kind` | `observed` (관측) 또는 `forecast` (예보). 비어 있으면 날씨 없음 |
| `weather_issued_at` | 예보 발표 시각. 예보일 때만 있음 |
| `exam_period` | 그날 시험 기간인 학교 수 (에이전트가 고른 학교만, 계획이 없으면 연세·서강·이화 전체) |
| `vacation` | 그날 방학인 학교 수 |
| `festival` | 그날 축제 중인 학교 수 |
| `nearby_event` | 그날 반경 안에서 진행 중인 문화행사 수 (그날 이전에 등록된 행사만) |

### events.json

| 필드 | 내용 |
|---|---|
| `event_id` | 학사일정 `{학교}-{시작일}-{유형}`, 서울시 행사 `seoul-{문화포털 코드}` |
| `source` | `academic` 또는 `seoul_culture` |
| `school` | 학사일정만: `yonsei`, `sogang`, `ewha` |
| `type` | 학사일정 `exam`, `festival`, `semester_start`, `semester_end`, `vacation_start`, `vacation` / 서울시 행사 `event` |
| `title` | 원문에 적힌 일정 이름 그대로 |
| `start_date`, `end_date` | 기간 |
| `source_url` | 원문 페이지 주소 |
| `published_at` | 게시 시각. 서울시 행사는 등록일, 학사일정 페이지에는 없어서 `null` |
| `fetched_at` | 원문을 저장한 시각 |
| `verified` | 검증 통과 여부 |
| `store_id`, `category`, `place`, `distance_m` | 서울시 행사만: 매장, 분류, 장소, 매장과의 거리 |

학사일정은 LLM이 원문에서 일정을 추출한 뒤, 제목이 원문에 실제로 있는지와 날짜가 해당 학기 범위 안인지 확인한 것만 남깁니다. `vacation`은 방학 시작일과 다음 개강일로 계산한 기간입니다.

## 배포

- **공개 시연 사이트:** `Dockerfile`이 화면을 빌드해 백엔드와 한 주소로 제공합니다. `DEMO_MODE=1`이면 보기 전용이고 `backend/demo_data/`의 결과(가상 매장, 공개 데이터)만 보여 줍니다. API 키가 필요 없습니다. Render는 `render.yaml`대로 만듭니다.
- **전체 기능:** 위 '웹 화면'대로 로컬에서 실행합니다.

## 기술 스택

| 영역 | 사용 기술 |
|---|---|
| 프론트엔드 | React, TypeScript, Vite, Tailwind CSS, TanStack Query |
| 백엔드 | Python, FastAPI |
| 예측 | CatBoost (다중 분위 회귀), pandas |
| LLM | Claude API (Anthropic SDK, 구조화 출력) |
| 외부 데이터 | 기상청 ASOS·단기예보, 한국천문연구원 특일 정보, 서울시 문화행사 정보, 카카오 로컬, NAVER API HUB 검색·검색어 트렌드, OpenStreetMap |
| 배포 | Docker, Render |

## 유의 사항

- 과거 날씨는 그때의 예보가 아니라 실제 관측값을 "전날 예보"처럼 씁니다(과거 예보는 구할 수 없음). 그래서 날씨 신호의 검증 성능은 실제 운영 때보다 조금 좋게 나올 수 있습니다. 실행 기록에 해당 줄 수가 표시됩니다.
- 뉴스·공지는 게시 시각 이전 날짜의 예측에 쓰지 않습니다. 게시 시각을 모르는 글은 읽은 시각에 공개된 것으로 봅니다.
- 협력 매장의 POS 데이터와 그 결과, API 키는 이 저장소에 포함하지 않습니다.
- 메뉴 검색량 유행은 지금 AI 주의 안내에만 쓰고 예측 모델 입력으로는 쓰지 않습니다.
- 예보는 24시간이 모두 있는 날짜만 기록합니다. 실행 시점의 오늘은 이미 지난 시간의 예보가 없어 비워 둡니다.
- 학사일정 수집기는 지금 연세·서강·이화만 지원합니다. 이화여대 학사일정에는 기말시험이 없어(학과별 시행) 이화의 기말 기간은 `exam_period`에 반영되지 않습니다.
- 아카라카, 연고전 같은 대학 축제는 학사일정 페이지에도 서울시 문화행사에도 없을 수 있습니다.
- 서울시 문화행사 중 14일보다 긴 행사(상설 전시 등)는 매일 1이 되어 신호가 되지 않으므로 뺍니다. 뉴스·블로그에서 찾은 팝업은 7일 이하만 신호로 쓰고, 더 긴 팝업은 여는 날 AI 주의 안내 자료로만 씁니다.
- 서울시 문화행사는 등록일 이후 날짜에만 셉니다. 다만 등록 후 수정·취소 이력은 API에서 알 수 없어, 과거 데이터에는 결국 열린 행사만 남아 있습니다.

## 팀

| 이름 | 역할 |
|---|---|
| 영찬 | PM, 데이터 형식·평가 기준 설계, 발표 |
| 새얼 | 데이터 수집 에이전트 |
| 동환 | 예측 엔진, LLM 판단 |
| 석현 | 프론트엔드, 배포 |
