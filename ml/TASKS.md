# ml/ 개발 명세 (담당: 김동환)

이 문서는 AI 코딩 도구(Claude Code)에 그대로 넣어 쓰는 작업 명세다. 저장소 규칙은 최상위 `CLAUDE.md`를 먼저 따른다.

## 0. 배경

- 서비스: **내일몇개**. 카페·베이커리의 POS 판매 기록 + 외부 신호(날씨·학사일정·행사·유행)로 **내일 메뉴별 판매량(p10·p50·p90)과 준비량**을 예측한다.
- 대회: 2026 연세 캠퍼스타운 AI 스타트업 해커톤. 본선 11/20(금). **코드 동결 11/18(수) 저녁.**
- 팀: 새얼(에이전트, `agent/`), 동환(예측 엔진, `ml/`), 석현(백엔드·프론트), 영찬(PM·데이터 형식 관리).
- 예측은 **매장 영업이 끝난 뒤 다음 날 하루**를 예측하는 상황을 가정한다 (예측 거리 h = 1일). 예측 시각 = 그 매장의 영업 종료 시각 (매장마다 다름, 모르면 21:00).

### 데이터 상황 (중요)

| 데이터 | 언제 | 비고 |
|---|---|---|
| 가상 POS·날씨·학사일정 | 지금 있음 | `data/sample/` (메뉴 11개, 2025-11-01 ~ 2026-10-31, 심어 둔 효과는 `truth.json`) |
| 실제 매장 POS | **성수동 카페 한 달치가 11/18에 들어옴** | 다른 매장은 섭외 중. 포스 종류·열 구성 미확인 |
| 에이전트 신호 (`signals.csv`) | 새얼이 11/14~16에 순차 제공 | 그 전까지는 가상 `signals.csv` 사용 |

→ **모든 코드는 가상 데이터로 끝까지 완성하고, 11/18에는 파일만 바꿔 끼워 하루 안에 결과가 나와야 한다.**
→ 실제 데이터가 한 달치뿐일 수 있으므로 **짧은 이력(4~5주)에서도 오류 없이 돌아가야 한다** (§6 짧은 데이터 모드).

## 1. 파일 구조 (ml 부분)

```
contracts/schemas.py   데이터 형식 (팀 공통, 바꾸면 팀에 공유)
ml/
  ingest.py            POS 엑셀 → SalesRow 표
  features.py          판매 이력·달력 변수 + 신호 붙이기 + 변수 묶음(M1~M3)
  models.py            M0 + CatBoost 다중 분위
  evaluate.py          지표, 시간순 교차검증, 신호 채택 → backtest.json
  predict.py           내일 예측, 근거, 준비량, LLM 특수 상황 경고 → forecast.json
  report/              (기존) 사장님용 판매 패턴 리포트
run.py                 한 매장 전체 실행
tests/test_ml.py       누수·지표·전체 실행 테스트
```

## 2. 데이터 형식 (contracts/schemas.py) — 1번 작업

기존 `SalesRow`, `SignalRow`, `Reason`, `ForecastRow`, `Forecast`를 유지하고 아래를 추가·수정한다. 바꾼 뒤 `contracts/examples/`와 `tests/test_contracts.py`도 같이 고친다.

- `SalesRow`: `date, store_id, menu, qty(int ≥ 0), sold_out(bool)` — 이미 `store_id` 있음, 유지.
- `SignalRow`: `date, store_id, signal, value(float), source_url, published_at(datetime), kind ∈ {observed, forecast, calendar, event}` — 세로형. 유지.
- `ForecastRow`: 기존 필드 + `prep_qty`는 준비량 기능에서 채움.
- `Forecast`에 추가:
  - `signals_used: list[str]` — 이 매장에서 채택된 신호 이름
  - `warnings: list[Warning]` — LLM 특수 상황 경고 (없으면 빈 리스트)
- 새 형식 `Warning`:
  ```python
  class Evidence(BaseModel):
      source_url: str
      quote: str                     # 원문 인용 (없으면 경고를 만들지 않음)

  class Warning(BaseModel):
      date: dt.date
      menu_scope: list[str]          # 영향 받는 메뉴, 전체면 ["*"]
      situation_type: Literal["유행급변", "대형행사", "기상특보", "휴무가능성", "데이터이상"]
      direction: Literal["증가", "감소", "불확실"]
      strength: Literal["낮음", "중간", "높음"]
      evidence: list[Evidence] = Field(min_length=1)
      message: str                   # 사장님께 보여 줄 한 문장
  ```
- 새 형식 `BacktestResult` (모델 비교 화면이 읽음):
  ```python
  class ModelScore(BaseModel):
      model: str                     # "M0", "M1", ...
      wape: float; mae: float; bias: float
      pinball_p10: float; pinball_p90: float
      coverage_80: float             # 실제값이 [p10, p90] 안에 든 비율
      n: int
      wape_by_fold: list[float]

  class SignalDecision(BaseModel):
      signal_group: str              # "weather", "events", ...
      signals: list[str]
      adopted: bool
      wape_change_pct: float         # 넣었을 때 WAPE 변화 (음수 = 개선)
      folds_improved: int; folds_total: int
      reason: str                    # 화면에 보여 줄 한 줄 (쉬운 한국어)

  class BacktestResult(BaseModel):
      store_id: str
      generated_at: dt.datetime
      folds: list[tuple[dt.date, dt.date]]
      test_period: tuple[dt.date, dt.date]
      cv_scores: list[ModelScore]     # 검증 구간 평균
      decisions: list[SignalDecision]
      chosen_model: str
      test_scores: list[ModelScore]   # 최종 테스트 (M0 vs 채택 모델), 한 번만 계산
      data_note: str                  # 예: "판매 기록 34일. 검증 구간이 짧아 결과의 변동이 큼"
  ```

## 3. 기능 명세

표기: **가상 OK** = 가상 데이터로 지금 개발 가능 / **일부** = 코드는 지금, 실제 결과는 데이터 도착 후 / **필요** = 데이터가 있어야 시작.

| # | 기능 | 파일 | 우선 | 실 POS 없이 | 에이전트 데이터 없이 |
|---|---|---|---|---|---|
| 1 | 데이터 형식 추가 (§2) | contracts/schemas.py | 반드시 | 가상 OK | 가상 OK |
| 2 | POS 엑셀 읽기 | ingest.py | 반드시 | 일부 (11/18 확정) | 가상 OK |
| 3 | 메뉴명 통일 후보·휴무·품절 | ingest.py | 반드시 | 가상 OK | 가상 OK |
| 4 | 판매 이력·달력 변수 | features.py | 반드시 | 가상 OK | 가상 OK |
| 5 | 신호 붙이기 (published_at 기준) | features.py | 반드시 | 가상 OK | 일부 |
| 6 | M0 + CatBoost M1~M3 | models.py | 반드시 | 가상 OK | 일부 (M1은 OK) |
| 7 | 지표 + 시간순 교차검증 + 최종 테스트 | evaluate.py | 반드시 | 가상 OK | 가상 OK |
| 8 | 신호 채택·제외 → backtest.json | evaluate.py | 반드시 | 일부 | 일부 |
| 9 | 내일 예측 + 근거 → forecast.json | predict.py | 반드시 | 가상 OK | 가상 OK |
| 10 | 준비량 | predict.py | 가능하면 | 가상 OK | 가상 OK |
| 11 | LLM 특수 상황 경고 (B안) | predict.py | 가능하면 | 가상 OK | 일부 |
| 12 | 전체 실행 연결 | run.py | 반드시 | 가상 OK | 가상 OK |
| 13 | 성수 카페 팝업 효과 분석 | 노트북 | 여유 있으면 | 필요 (11/18) | 필요 (팝업 일정) |
| 14 | 개선이 우연인지 검정 (블록 부트스트랩) | evaluate.py | 여유 있으면 | 가상 OK | 가상 OK |

### 2. POS 엑셀 읽기 (`ingest.py`)
- `read_pos(path, pos_type: Literal["toss", "okpos", "auto"]) -> pd.DataFrame[date, menu_raw, qty]`
- 실제 파일 형식을 아직 모른다. **열 이름 매핑을 딕셔너리 하나로 분리**해서 11/18에 그 딕셔너리만 고치면 되게 한다:
  ```python
  COLUMN_MAP = {
      "toss":  {"date": ["날짜", "판매일자", "일자"], "menu": ["상품명", "메뉴명"], "qty": ["수량", "판매수량"]},
      "okpos": {"date": ["일자", "영업일자"], "menu": ["상품명"], "qty": ["수량", "판매수량"]},
  }
  ```
  `auto`는 첫 시트의 머리글에서 후보 열 이름을 찾아 고른다. 머리글이 몇 번째 줄인지도 자동 탐색(위 10줄 안).
- 영수증 단위(판매 시각 포함) 파일이면 `date`별로 합산한다. 시각 열은 있으면 따로 보관(품절 시각 추정용, P1).
- 합계 행·취소(음수 수량) 행은 제외하고, 제외 건수를 로그로 남긴다.
- 개발용으로 `tests/fixtures/`에 **가상 토스·OKPOS 형식 엑셀**을 만든다 (열 이름은 추정, 11/18에 실제로 교체).

### 3. 메뉴명 통일·휴무·품절 (`ingest.py`)
- `suggest_menu_merges(menus) -> list[(a, b, score)]`: 문자열 유사도(공백·괄호·ICE/HOT 표기 정규화 후 `difflib` 비율)로 후보만 뽑는다. **자동 합치기 금지.** 승인된 규칙은 `data/artifacts/{store_id}/menu_map.json`에 저장하고 그것만 적용.
- 휴무: 전 메뉴 판매 합이 0인 날은 행 자체를 뺀다.
- 품절: 메뉴별로 같은 최댓값에서 3번 이상 멈추면 그 값과 같은 날을 `sold_out=True`로 표시 (기존 `ml/report/analyze.py` 로직 재사용).
- 최근 14일 판매가 없는 메뉴는 "단종"으로 보고 예측 대상에서 뺀다.
- 출력: `data/artifacts/{store_id}/sales_clean.csv` (SalesRow 형식).

### 4. 판매 이력·달력 변수 (`features.py`)
**시점 규칙 (미래 정보 누수 방지, 가장 중요):**
- D일 예측은 D-1일 영업 종료 직후에 낸다 → `issue_time(D, close_time) = D-1 + close_time`.
  - `close_time`은 매장 설정으로 받는다 (`data/artifacts/{store_id}/store.json`의 `close_time`, 없으면 21:00).
  - 자정 넘어 영업하는 매장은 `23:59`로 둔다 (그 뒤 판매는 다음 날로 집계되므로).
  - 영업 종료 후이므로 D-1일 판매(`lag_1`)는 쓸 수 있다.
- 판매 이력 변수는 D-1일까지만 쓴다. 모든 lag·이동평균은 `shift(1)` 다음에 계산한다.
- 메뉴별로 날짜를 달력 전체로 펼친 뒤(휴무일은 NaN) 계산한다.

변수:
- `lag_1, lag_7, lag_14`, `same_wd_mean_4`(지난 4주 같은 요일 평균), `mean_7`, `mean_28`(min_periods 7), `sold_out_7`(최근 7일 품절 횟수), `days_since_start`(메뉴 출시 후 경과일)
- 달력: `dow`, `is_weekend`, `is_holiday` (지금은 고정 목록, 새얼의 공휴일 신호가 오면 그것으로 교체)
- 범주형: `store_id`, `menu`

`build_frame(sales, signals, signal_names, predict_dates=None) -> pd.DataFrame`
- 학습용: 판매가 있는 모든 (매장, 메뉴, 날짜) 행.
- `predict_dates`를 주면 최근 14일 안에 팔린 메뉴마다 `qty=NaN`인 예측 행을 추가.

### 5. 신호 붙이기 (`features.py`)
- 입력은 세로형 `signals.csv`. `published_at <= issue_time(date, close_time)`인 행만 쓰고, 같은 (매장, 날짜, 신호)가 여러 번 있으면 **가장 늦게 공개된 값**.
- 세로형 → 가로형(신호마다 열 하나)으로 바꿔 붙인다.
- 빈 값: `kind`가 `calendar`/`event`면 0, `observed`/`forecast`면 NaN 그대로(CatBoost가 처리).
- 변수 묶음은 이름 목록으로만 관리한다. 새 신호는 목록에 이름만 추가:
  ```python
  SIGNAL_GROUPS = {
      "weather": ["temp_mean", "rain_mm"],
      "events":  ["exam_period", "vacation", "festival", "nearby_event"],
      "trend":   ["trend_level", "trend_slope"],
  }
  FEATURE_SETS = {"M1": [], "M2": ["weather"], "M3": ["weather", "events", "trend"]}
  ```
  `signals.csv`에 없는 신호 이름은 경고만 남기고 건너뛴다 (에러 내지 않음).
- 신호 이름 목록은 새얼과 합의한 것만 쓴다.

### 6. 모델 (`models.py`)
모든 모델은 같은 모양: `model.fit(train_frame)` → `model.predict(frame) -> DataFrame[p10, p50, p60, p80, p90]` (예측값 `pred` = p50).

- **M0** 지난주 같은 요일: `pred = lag_7` → 없으면 `same_wd_mean_4` → `mean_7`. 범위는 지난 4주 같은 요일의 최소~최대.
- **M1~M3** CatBoost, 매장·메뉴 전체를 **모델 하나**로 학습 (`store_id`, `menu`는 범주형).
  - 손실: `MultiQuantile:alpha=0.1,0.5,0.6,0.8,0.9`
  - 목표: **비율 목표** `y = qty / base`, `base = mean_28 → mean_7 → lag_1` 순서로 채우고 1 이상으로 자름. 예측 = 비율 예측 × base. (가게 성장·메뉴 규모 차이를 한 모델로 처리)
  - 분위 교차 방지: 예측 분위를 정렬. 음수는 0으로.
  - **품절일(`sold_out=True`)은 학습 목표에서 뺀다** (판매량 = 수요의 하한일 뿐). lag 계산에는 그대로 쓴다.
  - 기본값: `iterations=500, depth=6, learning_rate=0.05, random_seed=0`. 짧은 데이터 모드에서는 `iterations=200, depth=4`.
  - 학습 기간 신호 중앙값을 저장 (근거 계산에서 '평소 값'으로 씀).

### 7. 평가 (`evaluate.py`)
지표 (메인은 WAPE):
- `wape = Σ|y−p| / Σy`, `mae`, `bias = Σ(p−y) / Σy` (+면 많이 예측), `pinball(q)`, `coverage_80`.
- **품절일은 평가에서 뺀다.** 뺀 행 수를 `data_note`에 적는다.

시간순 교차검증 (rolling origin, 학습 기간을 늘려 가는 방식):
```
|------ 학습 ------|-검증1-|-검증2-|-검증3-|-검증4-|== 최종 테스트 ==|
검증 k: 그 구간 시작 전 데이터 전부로 새 모델 학습 → 구간의 각 날짜를 하루 앞 예측
        (구간 안에서는 재학습하지 않고, 변수만 매일 최신 판매로 갱신)
최종 테스트: 모델·신호를 모두 정한 뒤 딱 한 번
```
- 기본: 최종 테스트 28일, 검증 28일 × 4개.
- **짧은 데이터 모드** (판매 일수 < 120일): 최종 테스트 7일, 검증 7일 × 2개, 최소 학습 14일. 그래도 부족하면 최종 테스트 없이 검증만 하고 `data_note`에 명시.
- 최종 테스트 결과를 보고 신호나 모델을 바꾸지 않는다.

### 8. 신호 채택 (`evaluate.py`)
- 신호 묶음별로 "넣었을 때 vs 뺐을 때"를 같은 검증 구간에서 비교한다 (M1 → M2 → M3 순으로 하나씩 추가).
- **채택 조건:** 평균 WAPE가 줄고, 검증 구간의 과반에서 줄었을 때. 아니면 제외.
- 제외 이유를 쉬운 한국어로: `"비 예보는 이 매장 판매 예측을 개선하지 못해 쓰지 않음 (4개 구간 중 1개만 개선)"`.
- 채택된 묶음으로 `chosen_model`을 정하고, 그 모델과 M0만 최종 테스트.
- 출력: `data/artifacts/{store_id}/backtest.json` (BacktestResult).

### 9. 내일 예측 + 근거 (`predict.py`)
- 채택된 변수 묶음으로 **전체 데이터(최종 테스트 기간 포함)로 다시 학습** → 마지막 날 다음 날 예측.
- 근거(반사실 방식): 채택된 신호마다 그 값을 '평소 값'으로 바꿔 다시 예측하고 차이를 %로.
  - 평소 값: `rain_mm=0`, 이벤트류=0, 기온 등 연속값 = 학습 기간 중앙값.
  - |효과| ≥ 3%인 것만 `reasons`에 넣는다. 문장 예: `"비 예보(12mm)로 평소보다 약 13% 적게 예상"`.
  - 문장은 템플릿으로 만든다 (LLM 사용 안 함).
- 출력: `data/artifacts/{store_id}/forecast.json` (Forecast).

### 10. 준비량 (`predict.py`)
- 사장님 선택 3가지: `"폐기 줄이기"` → p60, `"균형"` → p50, `"품절 줄이기"` → p80. 올림해서 정수.
- 원가·판매가 정보가 있으면 신문팔이 공식 `q* = 품절비용 / (품절비용 + 폐기비용)`에 가장 가까운 분위를 쓴다 (P1).

### 11. LLM 특수 상황 경고 — B안 (`predict.py`)
- **숫자는 바꾸지 않는다. 경고만 만든다.** (`CLAUDE.md`: LLM은 판매량을 예측하지 않음)
- 입력 (웹 검색 없이, 새얼이 모은 것만):
  - 예측 날짜, 메뉴별 예측과 범위
  - `signals_used` (모델이 이미 쓴 신호 목록)
  - `collection.json`의 그날 전후 행사·뉴스·유행 정보 (원문 포함)
- 출력: `Warning` 리스트 (§2 형식). 규칙:
  - 이미 모델 변수에 들어간 상황이면 경고하지 않음 (같은 효과를 두 번 반영하지 않게)
  - 원문 인용(`evidence.quote`)이 없으면 경고하지 않음
  - 특별한 상황이 없으면 빈 리스트
  - 거리·날짜 차이·증가율 같은 숫자는 코드가 계산해서 넘김
- `temperature=0`, 입력 해시로 결과를 캐시해서 같은 입력은 다시 호출하지 않음. 데모에서는 저장된 결과를 씀.
- LLM 제공자와 모델 이름은 `.env`에서 읽는다 (본선 당일 쓸 수 있는 모델이 제한되므로 교체 가능하게). API 키를 코드나 로그에 넣지 않는다.
- 평가 (P1): 과거 경고 날의 실제 판매가 경고 방향으로 움직였는지 적중률. 50% 안팎이면 "참고 정보"로만 표시.

### 12. 전체 실행 (`run.py`)
```bash
python run.py --store sinchon-a --demo                            # 가상 데이터로 끝까지
python run.py --store seongsu-a --pos data/raw/seongsu-a.xlsx \
              --signals data/artifacts/seongsu-a/signals.csv     # 실데이터
```
순서: ingest → (signals 읽기) → evaluate → predict → `data/artifacts/{store_id}/`에 결과 파일 저장.
- 가상 데이터로 전체가 **2분 안에** 끝나야 한다.
- 각 단계 결과 파일이 이미 있으면 `--from-step`으로 중간부터 다시 실행.

### 13. 성수 카페 팝업 효과 분석 (여유 있으면, 11/18 이후)
- 데이터가 한 달치라 모델 검증보다 **기술 통계**로: 팝업 있는 날 vs 없는 날을 **같은 요일끼리** 비교.
- 팝업 일정(날짜·위치·공지일)은 새얼에게 요청.

## 4. 테스트 (`tests/test_ml.py`)
- **누수 테스트 1:** D일 이후 판매를 바꿔도 D일 행의 변수가 그대로인지.
- **누수 테스트 2:** `published_at`이 `issue_time(D, close_time)`보다 늦은 신호는 D일 행에 안 붙는지, 같은 신호의 이른 버전은 붙는지. `close_time`을 19:00과 23:00으로 바꿔 두 번 확인.
- **지표 테스트:** 예측 [55, 2, 50], 실제 [50, 1, 50] → WAPE = 6/101.
- **분위 테스트:** 모든 예측에서 p10 ≤ p50 ≤ p90, 모두 0 이상.
- **전체 실행 테스트:** `run.py --demo`가 `iterations=50`으로 끝까지 돌고, 결과 파일 3개가 계약 형식을 통과하는지.
- **짧은 데이터 테스트:** 가상 데이터를 35일로 잘라도 전체 실행이 에러 없이 끝나는지.
- PR 전에 `pytest -q` 통과.

## 5. 일정

| 날짜 | 할 일 | 필요한 데이터 |
|---|---|---|
| 11/12~13 | 1 → 4 → 6(M0·M1) → 7 → 9 → 12, 테스트. 가상 데이터로 끝까지 한 번 | 없음 |
| 11/14 | 2·3을 가상 토스·OKPOS 엑셀로. 5·6(M2·M3)을 가상 신호로 | 없음 |
| 11/15 | 8 신호 채택, 짧은 데이터 모드, 새얼 실제 신호 오면 교체 | 에이전트 데이터 |
| 11/16 | 11 LLM 경고(B안), 10 준비량 | 행사·뉴스 샘플 |
| 11/17 | 근거 문장 다듬기, 석현 화면과 연결 점검, 버그 수정 | 없음 |
| **11/18** | **성수 카페 데이터 도착 → COLUMN_MAP 수정 → `run.py` 실행 → 결과 고정.** 저녁 코드 동결 | 실 POS |
| 11/19 | 리허설. 시간 되면 13 팝업 분석 | 실 POS + 팝업 일정 |

## 6. 짧은 데이터 모드 (11/18 대비, 필수)
성수 카페는 한 달치(약 30일)라서 다음이 모두 자동으로 처리돼야 한다:
- `mean_28` 등 계산 안 되는 변수는 NaN으로 두고 진행 (CatBoost가 처리).
- 검증 구간·최종 테스트를 판매 일수에 맞게 자동 축소 (§7).
- `data_note`에 "판매 기록 N일, 결과 변동이 큼"을 자동으로 기록 → 화면과 발표에서 그대로 밝힌다.
- 실데이터 결과가 가상 데이터보다 나빠도 그대로 보고한다. 숫자를 맞추려고 신호나 모델을 고치지 않는다.

## 7. 하지 않을 것
- 무작위 분할 검증
- LLM에게 판매량 숫자를 직접 만들게 하거나 예측값을 수정하게 하기
- 실제 매장 데이터를 `data/raw/` 밖에 두거나 커밋하기
- 7일 이상 앞을 예측하기 (다음 날 하루만)
- 토스포스·OKPOS 외 포스 형식 전용 코드
