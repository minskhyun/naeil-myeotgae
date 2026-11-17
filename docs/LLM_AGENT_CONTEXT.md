# LLM·에이전트 개발 컨텍스트

> **기록용 문서입니다 (2026-11-16 계획).** 이후 구조가 바뀌었습니다: 날씨·학사일정·서울 행사는 `backend/collectors`가 맡고,
> `agent/weather.py`·`agent/build.py`는 없어졌습니다. 지금 구조는 맨 위 `README.md`와 `ml/REVIEW.md`를 보세요.

작성 2026-11-16. 새얼의 `signals.json`·`collection.json`이 오지 않아, 에이전트(외부 정보 수집 + LLM) 부분을 동환이 직접 만든다.
이 문서는 그 작업에 필요한 맥락을 한곳에 모은 것이다. 코드 동결 **11/18(수) 저녁**, 본선 11/20(금).

---

## 0. 지금 상태 한눈에

| 부분 | 상태 |
|---|---|
| 예측 엔진 `ml/` | 완성. 가상·프랑스 빵집 데이터로 검증 끝. `ml-engine` 브랜치에 푸시됨 |
| 신호 읽기 | 완성. `run.py --signals 파일.json`이 형식 검사 후 사용 |
| LLM 경고 `ml/alerts.py` | 11/16 실제 API로 시험 통과 (가상 매장 + 시험 원문) |
| 에이전트 `agent/` (신호·원문 수집) | **없음** → 이번에 만들 것 |
| 백엔드 `backend/` | **저장소에 없음** |
| 프런트엔드 `frontend/` | Vite·React 기본 템플릿 상태 (Tailwind, react-query, recharts, react-dropzone, papaparse 설치됨) |
| 실데이터 | 성수 카페 POS 한 달치 11/18 도착 예정 |

---

## 1. 원칙 (발표에서도 그대로 말할 것)

- **LLM은 판매량 숫자를 만들거나 바꾸지 않는다.** 예측은 판매 기록으로 학습한 CatBoost가 한다.
- LLM이 하는 일은 두 가지뿐이다.
  1. **구조화:** 행사 공지·기사 같은 글에서 날짜·장소·근처 여부를 뽑아 신호 행으로 만든다 (에이전트).
  2. **경고:** 모델이 모르는 특별한 상황을 원문 인용과 함께 알린다 (`ml/alerts.py`).
- 숫자 신호(기온·강수량)는 **반드시 출처 API의 값**을 쓴다. LLM이 추측한 숫자를 넣지 않는다.
- 외부 신호는 넣었을 때 과거 검증에서 오차가 줄어야만 채택된다 (`evaluate.pick_combo`). 쓸모없는 신호를 넣어도 예측이 망가지지 않는다.

---

## 2. 전체 흐름에서 에이전트의 자리

```
[매장 정보 store.json]
        │ (주소·좌표·영업 종료 시각)
        ▼
agent/ ──① 날씨 API ─────────────→ signals.json (temp_mean, rain_mm)
       ──② 행사·공지 수집 → LLM 추출 → signals.json (nearby_event, special_day …)
                                 └→ collection.json (원문)
        │
        ▼
run.py --pos POS파일 --signals signals.json   (+ collection.json)
  ingest → evaluate(신호 채택 여부 결정) → predict → alerts(LLM 경고)
        │
        ▼
forecast.json · backtest.json → backend → frontend
```

---

## 3. 만들 결과물 1: `{store_id}_signals.json`

`contracts/schemas.py`의 `SignalRow` 객체 목록. 신호 한 줄 = 객체 하나.

```json
[
  {"date": "2026-11-19", "store_id": "seongsu-a", "signal": "rain_mm", "value": 12.0,
   "source_url": "https://www.weather.go.kr/...", "published_at": "2026-11-18T17:00:00+09:00", "kind": "forecast"},
  {"date": "2026-11-21", "store_id": "seongsu-a", "signal": "nearby_event", "value": 1,
   "source_url": "https://팝업공지", "published_at": "2026-11-03T10:00:00+09:00", "kind": "event"}
]
```

| 필드 | 뜻 |
|---|---|
| `date` | 신호가 **해당하는 날** |
| `store_id` | `seongsu-a` 등. POS 실행 때 `--store`와 같아야 함 |
| `signal` | 아래 표의 이름만 (다른 이름은 모델이 무시) |
| `value` | 숫자 |
| `source_url` | 실제로 열리는 출처. 화면 근거 링크로 쓰임 |
| `published_at` | **그 정보가 처음 공개된 시각**, 한국 시간 `+09:00` |
| `kind` | `forecast` · `observed` · `calendar` · `event` |

### 가져올 신호

| 우선 | signal | value | kind | 비고 |
|---|---|---|---|---|
| **1** | `temp_mean` | 일평균 기온(℃) | **forecast 필수**, observed 선택 | POS 기간 전체 + 내일 |
| **1** | `rain_mm` | 일강수량(mm) | forecast 필수, observed 선택 | 위와 같음 |
| **1** | `nearby_event` | 1 (취소면 0) | event | 근처 팝업·공연·축제. 여러 날이면 날마다 한 줄 |
| 2 | `special_day` | 1 | calendar | 발렌타인·화이트데이·빼빼로데이·크리스마스(이브) |
| 2 | `exam_period`, `vacation`, `festival` | 1 | calendar | 근처 대학 일정이 매장에 영향이 있을 때만 |
| 보류 | `trend_level`, `trend_slope` | — | — | SignalRow에 메뉴 칸이 없어 메뉴별 유행은 형식부터 정해야 함 |

공휴일은 `ml/calendar_kr.py`에 들어 있어 따로 안 만든다 (2025~2026만 있음).

### 규칙 (틀리면 검증 결과가 거짓이 됨)

1. **`published_at`을 정직하게.** 모델은 예측 시각(전날 영업 종료, 기본 21:00) 이전에 공개된 줄만 쓴다 (`features.attach_signals`). 늦게 나온 정보를 일찍 나온 것처럼 적으면 미래 정보가 섞인다.
2. **날씨는 과거 기간도 '예보'가 필요하다.** 관측값은 그날이 끝난 뒤 공개되므로 그날 예측에 절대 쓰이지 않는다. 지금 모델은 observed를 전혀 쓰지 않는다. 같은 날짜에 예보가 여러 번 나왔으면 발표 시각마다 한 줄씩.
3. **하루 값으로 묶는 방법을 하나로 고정:** `temp_mean` = 그날 시간별 예보 기온(TMP) 평균 (어려우면 (TMN+TMX)/2), `rain_mm` = 그날 시간별 예보 강수량(PCP) 합. 17시 발표본 하나면 충분 (21시 이후 발표본은 어차피 버려짐).
4. **행사·달력 신호는 해당하는 날만 줄을 만든다.** 없는 날은 코드가 0으로 채운다. 같은 날 행사가 여럿이어도 한 줄. 취소되면 같은 날짜에 `value: 0` 줄을 취소 공지 시각으로 추가한다 (가장 늦게 공개된 값이 쓰이므로 자동 반영).
5. **"근처" 기준을 하나로:** 제안 = 매장에서 걸어서 10분 안팎(약 700m). 매장·기간마다 바꾸지 않는다.

---

## 4. 만들 결과물 2: `{store_id}_collection.json` (LLM 경고용 원문)

```json
[
  {"date": "2026-11-21", "title": "성수동 ○○ 팝업스토어 오픈", "text": "공지·기사 원문 그대로",
   "source_url": "https://...", "published_at": "2026-11-03T10:00:00+09:00"}
]
```

- `text`는 **요약하지 말고 원문 그대로**. 경고의 인용문이 원문에 글자 그대로 있는지 코드가 검사하고 없으면 버린다.
- `date`는 그 자료가 해당하는 날. 예측 날짜 ±1일 자료만 LLM에 넘어간다.
- 숫자 신호로 만들기 애매한 정보(공사, 유명인 방문 예고 등)도 여기에.
- 행사는 두 파일 모두에 넣는다: 숫자는 signals, 원문은 collection. 30일 데이터에서는 행사 신호가 채택되지 않을 가능성이 커서, 경고 쪽이 실제로 사장님께 전달되는 길이 된다.

---

## 5. 정보원 후보 (PROJECT_CONTEXT 6절 기준, 실제 사용 전 확인 필요)

| 신호 | 출처 | 확인할 것 |
|---|---|---|
| 날씨 예보 (서비스용, 내일) | 공공데이터포털 기상청 단기예보 조회서비스 | API 키 발급 시간, 매장 좌표 → 예보 격자(nx, ny) 변환 |
| 날씨 과거 예보 (학습용) | 기상자료개방포털 | **과거 단기예보 자료를 받을 수 있는지**. 안 되면 아래 '결정 필요' 1번 |
| 날씨 관측 (선택) | 기상자료개방포털 ASOS | 매장에서 가까운 관측소 |
| 지역 행사 | 서울 열린데이터광장 문화행사, 한국관광공사 TourAPI | 성수동 팝업이 실제로 들어 있는지 |
| 공연 | KOPIS | 매장 근처 공연장이 있을 때만 |
| 주변 시설 | 카카오 로컬 API | 근처 대학·공연장 파악 (선택) |
| 학사일정 | 대학 공식 웹페이지 | 근처 대학이 있을 때만 |

성수동 팝업은 공공 API에 잘 안 잡힐 수 있다. 시간이 없으면 **공지·기사 URL을 사람이 모으고, LLM이 날짜·장소·근처 여부만 뽑는 방식**이 현실적이다.

---

## 6. LLM 사용 지점과 방법

### 6-1. 에이전트: 글 → 구조화 (새로 만들 것)
- 입력: 공지·기사 원문(제목, 본문, URL, 공개 시각) + 매장 주소
- 출력(구조화 출력으로 형식 강제): `{is_event, start_date, end_date, place, near_store, cancelled, quote}`
- 코드가 할 일: 날짜 범위를 하루 단위 `nearby_event` 줄로 펼치기, `published_at`은 **글의 공개 시각을 코드가 넣기**(LLM에게 시각을 만들게 하지 않음), `quote`가 원문에 있는지 검사
- `near_store` 판단은 LLM보다 좌표 거리 계산이 정확하다. 장소를 뽑아 카카오 로컬로 좌표를 얻을 수 있으면 코드가 판단.

### 6-2. 경고: `ml/alerts.py` (이미 있음)
- `make_warnings(forecast, collection, cache_dir)`: 예측 날짜 ±1일 원문 + 메뉴별 예측 + `signals_used`를 LLM에 넘겨 `Warning` 목록을 받는다.
- 규칙(`SYSTEM` 프롬프트): 숫자 금지, 이미 채택된 신호와 같은 상황은 경고 안 함, 원문 인용·출처 필수, 없으면 빈 목록.
- 인용문이 원문에 글자 그대로 없으면 버림(`_quotes_are_real`). 입력 해시로 `llm_cache/`에 캐시 → 같은 입력은 다시 호출 안 함.
- 결과는 `forecast.json`의 `warnings`. 실패해도 예측은 경고 없이 저장된다.

### 6-3. 공통 설정
- `.env`(커밋 안 함): `ANTHROPIC_API_KEY=...`, 선택 `LLM_MODEL=...`, `LLM_PROVIDER=anthropic`
- 기본 모델 `claude-opus-5-5`. 이 모델은 `temperature` 지정을 거부하므로 쓰지 않고, 재현성은 캐시로 보장.
- 호출: `anthropic` SDK의 `messages.parse(..., output_format=PydanticModel)`로 형식 강제. 제공자 교체는 `alerts.PROVIDERS`.
- `pip install anthropic` 필요 (requirements.txt에 있음).
- 에이전트도 `alerts.settings()`와 같은 설정을 쓰게 하면 키 관리가 한곳에서 끝난다.

---

## 7. 이미 있는 코드 (재사용)

| 위치 | 하는 일 |
|---|---|
| `contracts/schemas.py` | `SignalRow`, `Warning`, `Evidence`, `Forecast` 형식 |
| `ml/features.py` `load_signals` | `.json`·`.csv` 모두 읽음, `+09:00`·`Z` 시각을 한국 시간으로 |
| `run.py` `_import_signals` | 신호 파일을 SignalRow로 한 줄씩 검사, 이 매장 줄만 `signals.csv`로 |
| `run.py` `step_predict` | `data/artifacts/{store}/collection.json`이 있으면 `make_warnings` 호출 |
| `ml/alerts.py` | 경고 생성 전체 |
| `tests/test_alerts.py` | 가짜 LLM으로 캐시·인용 검사·빈 결과 테스트 |
| `data/sample/sinchon-a/signals.csv` | 가상 신호 예시 (형식 참고용) |

---

## 8. 비어 있는 것 (할 일, 우선순위 순)

| # | 할 일 | 이유 | 크기 |
|---|---|---|---|
| 1 | ✅ (11/16) **`agent/` 날씨 수집** → signals.json (`agent/weather.py`, `agent/build.py`) | 과거 = ASOS 관측값 대용, 앞으로 = 실제 단기예보 | 중 |
| 2 | ✅ (11/16) **실제 LLM으로 경고 1회 시험** — 형식 강제 통과, 축제 경고·인용 일치, 이미 반영된 비 예보는 경고 안 함. `menu_scope`가 빈 목록으로 와서 코드가 `["*"]`로 정리 | 지금까지 API 호출 0회. 키·형식·비용 확인 | 소 |
| 3 | ✅ (11/16) `collection.json`을 `published_at`으로 거르기 | 지금은 예측 시각 뒤에 나온 글도 LLM에 넘어감 (과거 날짜로 돌리면 미래 정보 누수) | 소 |
| 4 | ✅ (11/16) `run.py --collection 파일` 옵션 + 형식 검사 (`contracts.CollectionItem`) | 지금은 artifacts 폴더에 손으로 복사해야 함 | 소 |
| 5 | ✅ (11/16) collection 중복 제거·원문 길이 제한 (3000자) | 비용·LLM 혼란 줄이기 | 소 |
| 6 | `agent/` 행사 수집 + LLM 추출 → nearby_event + collection | 성수 팝업 | 중~대 |
| 7 | ✅ (11/16) `special_day` 달력 (`agent/special_days.py`) | 날짜가 정해져 있음 | 소 |
| 8 | ✅ (11/16) 준비 방식 방향 수정 (`PREP_MODES`: 폐기 줄이기가 균형보다 많이 준비하는 문제) | 사장님 안내와 실제가 다름 | 소 |
| 9 | 백엔드: artifacts의 JSON을 돌려주는 최소 API | 웹 시연 | 중 |
| 10 | 프런트: forecast·backtest 화면 | 웹 시연 | 대 |

---

### 11/16 추가로 고친 것
- LLM에 `model_already_reflected`(모델이 내일 실제로 반영한 근거 문장)를 함께 넘긴다. 전에는 신호 **이름**(`signals_used`)만 넘겨서, `nearby_event`라는 이름만 보고 '행사는 이미 반영됨'으로 오해할 수 있었다.
- 가상 매장용 시험 원문 `data/sample/sinchon-a/collection.json` (가상 기사 4개: 경고해야 할 축제, 이미 반영된 비 예보, 예측 시각 뒤 공개된 공사 공지, 먼 날짜 행사).

### 11/16 날씨 결정과 확인 사항
- 단기예보 API는 **최근 3일 발표본만** 준다 ("최근 3일 간의 자료만 제공합니다"). https는 응답이 없어 http로 부른다.
- 기상자료개방포털에서 받은 `성수…_기온/강수/강수형태_202610.csv`는 시간당 값이 하나뿐(744줄 = 31일×24시간)이고 요소가 초단기실황과 같아 **예보가 아니라 실황(관측에 가까운 값)**으로 판단 → 쓰지 않음.
- 결정(동환): 학습용 과거 기간은 **ASOS 서울(108) 일자료를 '전날 17:10 예보'처럼** 넣는다. 이런 줄은 `source_url` 끝에 `#관측값을-예보-대신-사용` 표시가 붙고, `run.py`가 줄 수를 알려 준다. **발표·문서에서 "학습 기간 날씨는 실제 예보가 아니라 관측값"이라고 밝힌다.**
- 앞으로의 날짜는 실제 단기예보 17시 발표본(최근 3일 발표본 모두 보관).
- 매장 좌표는 지금 성수동 대략값(37.5446, 127.0557 → 격자 61,126). 실제 주소를 받으면 바꾼다.

## 9. 제안: `agent/` 최소 구조 (단순하게, 늘리기 쉽게)

```
agent/
  weather.py     매장 좌표 → 날씨 예보(과거·내일) → SignalRow 목록
  events.py      URL·원문 목록 → LLM 추출 → nearby_event 줄 + collection 항목
  calendar.py    special_day 등 정해진 날짜 → SignalRow 목록
  build.py       매장 하나: 위 결과를 합쳐 형식 검사 → data/raw/{store}_signals.json, _collection.json
```

- 출처마다 함수 하나, 결과는 모두 `SignalRow` 목록 → `build.py`가 합친다. 새 출처는 파일 하나 추가로 끝.
- 저장 전에 `SignalRow.model_validate`로 검사 (run.py와 같은 검사).
- API 응답 원본은 `data/raw/`에 캐시해서 같은 기간을 다시 받지 않게.

---

## 10. 검증 순서

1. **형식:** `python run.py --store seongsu-a --pos data/raw/<POS> --signals data/raw/seongsu-a_signals.json` → ingest 단계가 형식 오류를 줄 단위로 알려 줌.
2. **시점 규칙:** 신호마다 `published_at < date − 1일 + 영업 종료`인 줄이 있는지 확인 (없으면 그 신호는 전부 NaN으로 버려짐).
3. **채택 결과:** `backtest.json`의 `decisions`에서 날씨·행사가 채택됐는지와 이유. 채택 안 돼도 정상일 수 있다 (30일 데이터).
4. **경고:** 가상 매장(`--demo`)에 가짜 `collection.json`을 넣고 실제 API로 한 번 → `forecast.json`의 `warnings`와 인용 검사 확인.
5. **실데이터 전체:** 성수 POS + 실제 signals + collection으로 한 번에.

---

## 11. 결정이 필요한 것

1. **과거 날씨 예보를 못 구하면?** (가) 학습 기간 날씨는 비워 두고 내일 예보만 넣음 → 날씨 신호는 사실상 평가 불가 / (나) 과거 관측값을 '예보'로 간주해 넣음 → 성능이 실제보다 좋게 나오므로 `data_note`·발표에 반드시 밝혀야 함
2. "근처" 기준: 걸어서 10분(약 700m)으로 할지
3. 유행 신호: 이번에는 보류할지
4. `collection.json`에 `published_at`을 필수로 할지 (지금 alerts.py는 이 칸을 읽지 않음, 8번 표 3번과 연결)
5. 웹: 백엔드 없이 프런트가 JSON 파일을 직접 읽는 방식으로 시연할지, FastAPI를 둘지 (석현과 상의)

---

## 12. 제안 일정

| 날짜 | 할 일 |
|---|---|
| 11/16(오늘) | 8번 표 2·3·4 (LLM 실제 1회 시험, collection 보완), 날씨 API 키 신청·좌표 확인 |
| 11/17 | `agent/weather.py`, `calendar.py`, `build.py` → 가상·성수 기간 signals.json 생성, 백엔드 최소 API |
| 11/18 | 성수 POS 도착 → 전체 실행 → 결과 고정, 행사(events.py)는 시간 되는 만큼, 저녁 코드 동결 |
| 11/19 | 화면 연결 점검, 리허설 |
