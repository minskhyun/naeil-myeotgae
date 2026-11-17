# naeil-myeotgae
# 내일몇개

> 매장 POS 데이터와 주변 외부 신호(날씨·행사·학사일정·유행)를 함께 분석해, **메뉴별 내일 판매량 범위와 준비량**을 알려주는 AI 수요 예측 서비스

2026 연세 캠퍼스타운 AI 스타트업 해커톤 본선 프로토타입

## 문제

소상공인 사장님은 "내일 몇 개 만들어야 할까?"를 대부분 감으로 정합니다. 적게 만들면 품절, 많이 만들면 폐기가 생깁니다. 특히 유행 메뉴나 대학 행사처럼 매장 데이터만으로는 알 수 없는 변수가 판매량을 크게 흔듭니다.

## 해결 방법

1. **입력**: 사장님이 POS 데이터 1년치(날짜·메뉴별 판매량)를 업로드
2. **외부 데이터 수집**: LLM 에이전트가 매장 주변 정보원을 찾고, 공공 API·학사일정·뉴스·유행 신호를 수집해 구조화
3. **예측**: CatBoost로 4개 모델(M0~M3)을 비교해 어떤 신호가 실제로 오차를 줄이는지 검증하고, 판매량 범위(p10·p50·p90)를 예측
4. **LLM 판단**: 모델이 모르는 특수 상황(유행 급변, 대형 행사 등)을 근거 인용과 함께 경고. 예측 숫자는 LLM이 바꾸지 않음
5. **화면**: 예측 범위, 준비량, 근거, 경고를 사장님이 이해하기 쉬운 대시보드로 제공

### 모델 비교

| 모델 | 구성 |
|---|---|
| M0 | 전주 같은 요일 판매량 (기준선) |
| M1 | POS 이력 + 요일·계절성 + 날짜 효과 |
| M2 | M1 + 날씨 |
| M3 | M2 + 행사·학사일정·유행 신호 |

평가 지표는 WAPE(주 지표), MAE, 편향이며 시간순으로 분할한 테스트 기간에서 평가합니다.

## 기술 스택

| 영역 | 사용 기술 |
|---|---|
| 프론트엔드 | React, TypeScript, Vite, Tailwind CSS, Recharts |
| 백엔드 | Python, FastAPI |
| 예측 | CatBoost (분위수 회귀) |
| 데이터 수집 | Gemini API (정보원 선택, 학사일정 추출), 카카오 로컬, 서울시 문화행사 정보, 기상청 ASOS·단기예보, 한국천문연구원 특일 정보 |
| 배포 | Vercel (프론트엔드) |

## 폴더 구조

```
.
├── frontend/   웹 프로토타입
├── backend/    FastAPI, 데이터 수집, 예측 엔진
│   ├── collectors/   외부 신호 수집기와 정보원 탐색 에이전트, 매장 설정(stores.json)
│   └── data/         수집 결과 (external_daily.csv, events.json, 매장별 주변 시설·정보원 계획, 원문)
└── README.md
```

## 실행 방법

### 프론트엔드

```bash
cd frontend
npm install
npm run dev
```

http://localhost:5173에서 확인할 수 있습니다. 기본값은 public/mock/의 샘플 데이터를 사용하는 데모 모드입니다.

### 백엔드: 외부 데이터 수집

Python 3.11 이상이 필요합니다.

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

`backend/.env`에 API 키를 넣습니다. 이 파일은 저장소에 올리지 않습니다.

```
DATA_GO_KR_KEY=공공데이터포털 인증키 (Decoding)
KAKAO_REST_KEY=카카오 디벨로퍼스 REST API 키
SEOUL_DATA_KEY=서울 열린데이터광장 인증키
GEMINI_API_KEY=Google AI Studio 키
GEMINI_MODEL=gemini-flash-lite-latest
```

공공데이터포털에서 아래 세 API를 활용신청해야 합니다.

- 기상청_지상(종관, ASOS) 일자료 조회서비스
- 기상청_단기예보 조회서비스
- 한국천문연구원_특일 정보

매장 정보는 `collectors/stores.json`에 적습니다. `address`를 넣으면 카카오 API로 좌표를 찾아 `lat`, `lon`을 채웁니다.

전체 수집은 한 줄로 실행합니다.

```bash
python -m collectors.run_all                  # 2025-11-01 ~ 어제
python -m collectors.run_all --replan         # 매장 주소를 바꿨을 때: 주변 시설과 정보원 선택부터 다시
python -m collectors.run_all --refresh-events # 서울시 행사 목록 새로 받기
```

`run_all`은 아래 순서로 실행합니다. `build_external_daily`가 `external_daily.csv`를 새로 쓰므로 단계를 따로 실행할 때도 이 순서를 지켜야 합니다.

| 순서 | 모듈 | 하는 일 |
|---|---|---|
| 1 | `kakao` | 매장 좌표와 주변 시설(학교, 문화시설, 관광명소, 지하철역, 공연장, 경기장) 조회 |
| 2 | `agent` | 주변 시설을 보고 LLM이 이 매장에 쓸 학교와 행사 반경을 선택 |
| 3 | `build_external_daily` | 날짜 효과, 공휴일, 관측 날씨로 CSV 새로 만들기 |
| 4 | `forecast` | 단기예보로 내일·모레 날씨 추가 |
| 5 | `academic` | 학사일정 추출, 선택된 학교만 CSV에 반영 |
| 6 | `seoul_events` | 반경 안 문화행사를 CSV에 반영 |

1, 2단계는 결과 파일이 이미 있으면 건너뜁니다.

#### 정보원 탐색 에이전트

`agent`는 매장 주변 시설 목록을 LLM에 보여주고 "이 매장 판매량에 영향을 줄 정보원"을 고르게 합니다. 결과는 코드가 다시 검증합니다.

- 학교는 수집기가 있는 학교만, 주변 시설 목록에 실제로 있는 이름을 근거로 댄 경우만, 3km 이내만 인정합니다.
- 행사 반경은 300~2000m로 제한합니다.
- 지금은 수집할 수 없지만 중요해 보이는 정보원(다른 대학, 경기장 일정 등)은 `candidates`에 남겨 다음 수집기 후보로 씁니다.
- LLM 호출이 실패하면 거리 규칙(2km 안 캠퍼스, 반경 1000m)으로 대신 정합니다. `python -m collectors.agent --rule`로 직접 쓸 수도 있습니다.

결과는 `data/stores/{store_id}_sources.json`에 근거, 이유, 검증 메모와 함께 저장되어 대시보드에서 "왜 이 정보를 썼는지"를 보여주는 데 씁니다.

학사일정 원문은 `data/raw/academic/{학교}_{학기}.txt`에 저장되고, 파일이 있으면 다시 내려받지 않습니다. 자동으로 못 가져오는 학기는 페이지를 복사해 같은 이름으로 저장하고 `collectors/academic_sources.json`에 학기와 날짜 범위를 추가하면 됩니다.

## 데이터 형식

| 파일 | 내용 |
|---|---|
| `sales.csv` | date, time, menu, category, qty, soldout |
| `external_daily.csv` | 날씨, 날짜 효과, 행사, 학사 기간, 유행 변수 (아래 표) |
| `events.json` | 주변 행사·학사일정 (출처 URL, 게시 시각 포함, 아래 표) |
| `menu_trend_map.json` | POS 메뉴명 ↔ 유행 키워드 연결 |
| `predictions.json` | 메뉴별 p10·p50·p90, 사용 모델, 준비량 |
| `judgment.json` | LLM 특수 상황 경고와 근거 |

### external_daily.csv

날짜당 한 줄입니다. 현재 서울 관측소와 신촌 격자 기준입니다.

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

## 평가 결과

(최종 수치 확정 후 작성 예정)

## 유의 사항

- 과거 날씨는 예보가 아닌 실제 관측값을 사용하므로, 실제 운영 때보다 성능이 좋게 나올 수 있습니다.
- 뉴스·공지는 게시 시각 이전 날짜의 예측에 사용하지 않습니다.
- 협력 매장의 POS 데이터와 API 키는 이 저장소에 포함하지 않습니다.
- 예보는 24시간이 모두 있는 날짜만 기록합니다. 실행 시점의 오늘은 이미 지난 시간의 예보가 없어 비워 둡니다.
- 이화여대 학사일정에는 기말시험이 없어(학과별 시행) 이화의 기말 기간은 `exam_period`에 반영되지 않습니다.
- 아카라카, 연고전 같은 대학 축제는 학사일정 페이지에도 서울시 문화행사에도 없을 수 있어 별도 수집이 필요합니다.
- 서울시 문화행사 중 14일보다 긴 행사(상설 전시 등)는 매일 1이 되어 신호가 되지 않으므로 뺍니다.
- 서울시 문화행사는 등록일 이후 날짜에만 셉니다. 다만 등록 후 수정·취소 이력은 API에서 알 수 없어, 과거 데이터에는 결국 열린 행사만 남아 있습니다.

## 팀

| 이름 | 역할 |
|---|---|
| 영찬 | PM, 데이터 형식·평가 기준 설계, 발표 |
| 혜윤 | 데이터 수집 에이전트 |
| 동환 | 예측 엔진, LLM 판단 |
| 석현 | 프론트엔드, 배포 |
