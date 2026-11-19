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
웹 화면: 내일 준비표 · 얼마나 맞나 · 주변 정보 · 데이터 올리기(매장 추가)
```

### AI를 쓰는 곳

판매량 숫자는 판매 기록으로 학습한 예측 모델(CatBoost)이 만듭니다. **LLM(Claude)은 판매량을 만들거나 고치지 않습니다.** 정보를 찾고 정리하고, 행사의 성격(규모, 가게·메뉴와의 연관도)을 1~5로 매기고, 주의 문장을 씁니다. LLM이 매긴 값은 다른 주변 정보와 똑같이 모델의 입력 후보일 뿐이고, 지난 기록으로 시험해 예측이 실제로 나아질 때만 쓰입니다.

| 하는 일 | 파일 | 코드가 다시 확인하는 것 |
|---|---|---|
| 이 매장에 쓸 정보원 고르기 (어느 학교, 행사 반경) | `backend/collectors/agent.py` | 주변 시설 목록에 실제로 있는 이름만 인정, 반경 300~2000m |
| 학사일정 페이지에서 일정 뽑기 | `backend/collectors/academic.py` | 제목이 원문에 있는지, 날짜가 학기 범위 안인지 |
| 뉴스·블로그·공지 글에서 행사 날짜·장소 뽑기 | `agent/events.py` | 근거 문장이 원문에 그대로 있는지, 매장에서 1km 안인지 |
| 근처 행사의 규모와 가게·메뉴와의 연관도 매기기 (1~5) | `agent/relevance.py` | 점수는 1~5로 자르고 가게에 있는 메뉴 이름만 인정. 거리는 코드가 계산. 쓸지는 검증이 정함 |
| 기념일마다 가게·메뉴와의 연관도 매기기 (1~5) | `agent/relevance.py` | 위와 같음. 기념일 목록은 코드에 정해져 있음(`agent/special_days.py`) |
| 내일의 특별한 상황 알리기 (AI 주의 안내) | `ml/alerts.py` | 인용문이 원문에 그대로 있는지, 예측 시각 뒤에 공개된 글은 제외 |

같은 입력은 응답을 저장해 두고 다시 부르지 않습니다. 시연 때 결과가 바뀌지 않고 비용도 한 번만 듭니다.

### 모델 비교

| 모델 | 구성 |
|---|---|
| M0 | 지난주 같은 요일 판매량 (기준선) |
| M1 | 판매 이력 + 요일·공휴일 (CatBoost) |
| M2 | M1 + 날씨 |
| M3 | M2 + 학사일정·행사·기념일·메뉴 유행(검색량) |

- 외부 정보는 묶음(날씨 / 학사일정·행사 / 유행 / 기념일)의 **모든 조합**을 같은 검증 구간에서 비교합니다. M1보다 전체 오차(WAPE)가 3% 이상 줄고 검증 구간 과반에서 나아진 조합만 채택하고, 조합 안에서 빼도 나빠지지 않는 묶음은 뺍니다. 개선이 없으면 M1을 그대로 씁니다.
- 예측은 범위(p10~p90)로 냅니다. 준비량은 폐기 줄이기 p40, 균형 p50, 품절 줄이기 p80입니다.
- **시점 규칙:** D일 예측은 D−1일 영업 종료 시각에 낸 것으로 봅니다. 그 시각 뒤에 공개된 날씨 예보·뉴스·공지는 학습과 검증에 쓰지 않습니다.
- **메뉴 유행:** 메뉴 이름의 네이버 검색량으로 메뉴마다 "최근 7일 ÷ 그 전 4주"를 날짜별로 만듭니다(1이면 평소와 같음). D일 값은 D−2일까지의 검색량만 씁니다. 다른 정보와 똑같이 검증에서 오차를 줄일 때만 모델이 쓰고, 검색량이 30% 넘게 바뀐 메뉴는 AI 주의 안내에도 넘깁니다.

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

웹 화면의 '데이터 올리기'(로그인을 켰으면 '매장 추가')에서 매장 주소와 POS 파일(토스·OKPOS 엑셀 또는 CSV)을 올리거나, 명령줄에서 실행합니다.

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
LLM_MODEL=claude-opus-5-5          # 선택 (기본값): AI 주의 안내, 정보원 선택, 학사일정
LLM_MODEL_LIGHT=claude-haiku-5-5   # 선택 (기본값): 행사 글 추출 (글마다 한 번이라 가벼운 모델)
```

| 키 | 쓰는 곳 | 신청할 것 |
|---|---|---|
| `ANTHROPIC_API_KEY` | 위 표의 LLM 네 곳 | Anthropic Console |
| `DATA_GO_KR_KEY` | 날씨, 공휴일 | 공공데이터포털에서 '기상청_지상(종관, ASOS) 일자료 조회서비스', '기상청_단기예보 조회서비스', '한국천문연구원_특일 정보' 활용신청 |
| `SEOUL_DATA_KEY` | 서울 문화행사 | 서울 열린데이터광장 '서울시 문화행사 정보' |
| `KAKAO_REST_KEY` | 주변 시설, 주소·장소 → 좌표 | 카카오 디벨로퍼스 (없으면 좌표는 OpenStreetMap으로 찾음) |
| `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` | 뉴스·블로그 검색, 검색어 트렌드 | NAVER API HUB (2026-07-31부터 신규 키는 여기서만 발급) |

### 로그인 (선택)

`.env`에 구글이나 카카오 로그인 설정을 넣으면 로그인이 켜집니다(둘 다 넣어도 됨). 둘 다 없으면 로그인 없이 혼자 쓰는 방식(모든 매장을 보고 고침)으로 동작합니다.

```
GOOGLE_CLIENT_ID=구글 클라우드의 OAuth 클라이언트 ID (….apps.googleusercontent.com)
KAKAO_LOGIN=1                                          # 카카오 로그인 켜기 (KAKAO_REST_KEY를 그대로 씀)
KAKAO_CLIENT_SECRET=카카오 REST API 키의 클라이언트 시크릿   # 콘솔에서 시크릿이 켜져 있을 때 (기본이 켜짐)
ADMIN_EMAILS=관리자 이메일 (여러 명이면 쉼표로)            # 선택
```

**구글** — [Google Cloud Console](https://console.cloud.google.com/) → API 및 서비스 → OAuth 동의 화면을 만든 뒤(여기 적은 앱 이름이 로그인 창에 나옴), 사용자 인증 정보 → OAuth 클라이언트 ID → 유형 '웹 애플리케이션'. **승인된 자바스크립트 원본**에 화면을 여는 주소를 모두 넣습니다: `http://localhost`, `http://localhost:5173`, `http://localhost:8000`, 배포 주소(`https://….onrender.com`). 리디렉션 URI와 클라이언트 보안 비밀은 쓰지 않습니다.

**카카오** — [카카오 디벨로퍼스](https://developers.kakao.com/)의 앱 관리 페이지에서 (지도 검색에 쓰는 그 앱 그대로)

1. [카카오 로그인] > [사용 설정] > 상태 ON
2. [앱] > [플랫폼 키] > [REST API 키]에서 **리다이렉트 URI** 등록: 화면을 여는 주소마다 뒤에 `/api/auth/kakao/callback`을 붙여서 — `http://localhost:5173/api/auth/kakao/callback`, `http://localhost:8000/api/auth/kakao/callback`, 배포 주소
3. 같은 곳의 **클라이언트 시크릿** 값을 `.env`의 `KAKAO_CLIENT_SECRET`에 (시크릿을 꺼 두었으면 비워 둠)
4. [카카오 로그인] > [동의항목]에서 닉네임을 설정. 카카오계정(이메일)은 선택이며 없어도 로그인됩니다

같은 사람이 구글과 카카오로 각각 로그인하면 서로 다른 계정입니다(이메일이 같아도 합치지 않음). 카카오는 인증된 이메일을 받았을 때만 `ADMIN_EMAILS`와 비교합니다.

로그인이 켜졌을 때의 규칙 (`backend/app/auth.py`):

| 누가 | 볼 수 있는 매장 | 고칠 수 있는 매장 |
|---|---|---|
| 로그인 안 한 사람 | 시연 매장(`backend/demo_data`에 있는 ID) | 없음 |
| 로그인한 사람 | 시연 매장 + 내 매장 | 내 매장 (한 사람당 10개까지) |
| 관리자 (`ADMIN_EMAILS`) | 모든 매장 (명령줄로 만든 주인 없는 매장 포함) | 모든 매장 |

화면은 로그인 여부에 따라 둘로 나뉩니다 (`frontend/src/App.tsx`가 고름).

- **로그인 전 (`Landing.tsx`)**: 가상 매장을 예시로 제품을 한 쪽에 차례로 보여 줍니다. ① 내일 준비표 ② 어떤 주변 정보를 썼나 ③ 얼마나 맞나. 공개 시연 사이트(`DEMO_MODE=1`)도 이 화면입니다. 주소에 `?store=fr-bakery`를 붙이면 프랑스 빵집(공개 실데이터) 결과로 바뀝니다.
- **로그인 후 (`Workspace.tsx`)**: 예시 매장은 사라지고 내 매장만 보입니다. 탭 없이 고른 매장의 결과를 한눈에 보여 줍니다(`Dashboard.tsx`): 맨 위에 요약 숫자 네 칸(준비할 양, 평소와 다른 메뉴, 예상 범위 안에 든 비율, 주의할 소식), 왼쪽에 메뉴별 준비표, 오른쪽에 AI 주의 안내·예측에 쓴 주변 정보·얼마나 맞나 카드. 주변 정보와 검증의 전체 내용은 카드의 '자세히'를 누르면 창으로 뜹니다. 위쪽의 '매장 추가'를 누르면 창이 떠서 매장 이름, 위치, 닫는 시간을 적고 판매 기록 파일을 올립니다(매장 ID는 서버가 지어 줌). '매장 관리' 창에서 이름을 바꾸고, 판매 기록을 다시 올리고, 매장을 지울 수 있습니다. 지우면 그 매장의 결과 폴더와 올린 POS 파일이 모두 삭제됩니다.
- 로그인을 켜지 않은 서버는 처음부터 작업 화면이고 모든 매장이 보입니다(단추 이름은 '데이터 올리기', 매장 ID를 직접 적음).
- **분석 중 화면 (`AnalysisView.tsx`)**: '분석 및 예측하기'를 누르면 화면 전체에 뜹니다. 서버가 실행 중에 찾은 것을 한 건씩 알려 주고(`ml/progress.py`), 화면은 그것을 지도(Leaflet + OpenStreetMap) 위에 그립니다: 매장으로 날아가 내려앉고, 주변 시설이 점으로 돋아나고, 날씨·행사·소식·검색량이 빛줄기가 되어 가게로 들어옵니다. 끝나면 무엇을 모았고, 무엇을 썼고, 얼마나 맞고, 내일 무엇을 준비하면 되는지 정리해 보여 줍니다. 닫아도 분석은 계속되고, 끝난 뒤에는 '분석 과정 다시 보기'로 다시 볼 수 있습니다.

- 비밀번호는 받지 않습니다. 구글·카카오에서 받는 것은 이름(닉네임)·이메일·프로필 사진 주소뿐이고, `data/app.db`(SQLite, 저장소에 올리지 않음)에 저장합니다.
- 로그인 상태는 30일 유지되는 쿠키입니다(자바스크립트가 읽지 못하는 HttpOnly, https에서는 Secure). 서버에는 세션 번호의 해시만 저장합니다.
- 시연 모드(`DEMO_MODE=1`)는 보기 전용이라 로그인 버튼이 나오지 않습니다.

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
│   ├── progress.py         실행 중에 찾은 것을 한 건씩 알리기 (웹의 '분석 중' 화면용)
│   ├── paths.py            폴더 위치
│   ├── calendar_kr.py      공휴일 목록
│   ├── sample_data.py      가상 매장 만들기
│   └── REVIEW.md           판단 기록, 알려진 한계, 코드 지도
├── agent/                  주변 정보 수집
│   ├── collect.py          입구: 정보원 목록(SOURCES)을 차례로 실행해 합침
│   ├── collectors_bridge.py   공공 데이터 수집기 실행 + 결과를 예측 엔진 입력으로 변환
│   ├── report.py           수집 결과 요약 → sources_report.json (화면 '주변 정보')
│   ├── events.py           뉴스·블로그·공지 글에서 행사 추출
│   ├── naver.py            네이버 뉴스·블로그 검색, 메뉴 검색량
│   ├── geocode.py          주소·장소 → 좌표
│   ├── relevance.py        근처 행사를 규모·거리·가게(메뉴)와의 연관도로 따지기
│   └── special_days.py     기념일 (당일, 앞둔 날)
├── backend/
│   ├── app/main.py         웹 API (FastAPI)
│   ├── app/auth.py         구글 로그인, 매장 접근 권한 (SQLite)
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
| `signals.csv` | 모델에 넣는 외부 신호 (날짜, 신호 이름, 메뉴(메뉴별 신호만), 값, 출처, 공개 시각) |
| `collection.json` | AI 주의 안내에 쓰는 행사·뉴스 원문 |
| `sources_report.json` | 주변 정보 수집 요약: AI가 고른 정보원과 이유, 모은 신호, 찾은 행사·뉴스 (화면 '주변 정보') |
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
| LLM 모델·제공자 바꾸기 | `.env`의 `LLM_MODEL`·`LLM_MODEL_LIGHT`, `ml/llm.py`의 `PROVIDERS` |
| 로그인·권한 규칙 바꾸기 | `backend/app/auth.py`의 `can_read`·`can_write`·`check_write` (화면은 `frontend/src/Auth.tsx`) |
| 내 매장 관리 바꾸기 | `backend/app/main.py`의 `/api/my/stores`, `frontend/src/StoresView.tsx` (한 사람당 매장 수는 `auth.MAX_STORES`) |
| 로그인 후 화면 배치·창 바꾸기 | `frontend/src/Workspace.tsx` (창 틀은 `Modal.tsx`, 매장 추가 창은 `UploadView.tsx`), 결과 화면의 배치는 `Dashboard.tsx` |
| 분석 중 화면에 새 정보 보여 주기 | 파이썬에서 `progress.emit("종류", …)` → `frontend/src/api.ts`의 `ProgressEvent`에 종류 추가 → `AnalysisView.tsx`의 `line`(목록), `AnalysisMap.tsx`(지도) |
| 색·둥근 모양 같은 전체 분위기 | `frontend/src/index.css`의 `@theme` (지도 위 표시와 움직임은 같은 파일의 `nm-…`) |
| 로그인 전 첫 화면 바꾸기 | `frontend/src/Landing.tsx` (처음 보여 줄 예시 매장 `FIRST_EXAMPLE`, 메뉴 수 `MENUS_SHOWN`) |

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

결과는 `{store_id}_sources.json`에 근거, 이유, 검증 메모와 함께 저장되고, 웹 화면의 '주변 정보'에서 볼 수 있습니다.

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
- **로그인을 켠 채로 배포하려면:** `DEMO_MODE=0`, 로그인 설정과 API 키들을 환경 변수로 넣고, 구글 콘솔의 승인된 원본과 카카오 콘솔의 리다이렉트 URI에 배포 주소를 추가합니다. `data/`(사용자 DB, 올린 파일, 결과)가 지워지지 않는 디스크에 있어야 합니다. Render 무료 요금제는 다시 배포할 때마다 디스크가 비워지므로 유료 디스크나 외부 DB가 필요합니다.

## 기술 스택

| 영역 | 사용 기술 |
|---|---|
| 프론트엔드 | React, TypeScript, Vite, Tailwind CSS, TanStack Query, Leaflet(지도, OpenStreetMap) |
| 백엔드 | Python, FastAPI, SQLite(사용자·로그인·매장 주인), 구글 로그인(Google Identity Services), 카카오 로그인(REST API) |
| 예측 | CatBoost (다중 분위 회귀), pandas |
| LLM | Claude API (Anthropic SDK, 구조화 출력) |
| 외부 데이터 | 기상청 ASOS·단기예보, 한국천문연구원 특일 정보, 서울시 문화행사 정보, 카카오 로컬, NAVER API HUB 검색·검색어 트렌드, OpenStreetMap |
| 배포 | Docker, Render |

## 유의 사항

- 과거 날씨는 그때의 예보가 아니라 실제 관측값을 "전날 예보"처럼 씁니다(과거 예보는 구할 수 없음). 그래서 날씨 신호의 검증 성능은 실제 운영 때보다 조금 좋게 나올 수 있습니다. 실행 기록에 해당 줄 수가 표시됩니다.
- 뉴스·공지는 게시 시각 이전 날짜의 예측에 쓰지 않습니다. 게시 시각을 모르는 글은 읽은 시각에 공개된 것으로 봅니다.
- 협력 매장의 POS 데이터와 그 결과, API 키는 이 저장소에 포함하지 않습니다.
- 메뉴 유행 신호는 가상 매장과 프랑스 베이커리에서는 확인할 수 없어(가상 판매는 실제 검색량과 무관, 프랑스 메뉴는 한국 검색량과 무관) 효과가 아직 검증되지 않았습니다. 실제 매장 데이터에서 채택 여부를 그대로 보고합니다.
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
