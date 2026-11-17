"내일몇개" 예측 엔진의 **개발자용 설명서**를 A4 **정확히 세 장**으로 만들어 주세요. 결과물은 브라우저에서 PDF로 인쇄할 **HTML 파일 하나**입니다.

<목적>
처음 이 코드를 보는 팀원이 이 세 장만 보고 (1) 데이터가 어디서 들어와 어디로 나가는지, (2) 어느 파일의 어느 함수가 무엇을 하는지, (3) 주고받는 데이터와 변수가 어떤 구조인지 알고, 고칠 곳을 바로 찾을 수 있게 하는 것이 목적입니다.
읽기 좋아야 실제로 읽힙니다. 정보를 빠짐없이 나열하는 것보다 **찾아보기 쉬운 구조**가 더 중요합니다.
</목적>

<읽는 사람>
- 팀 개발자: 백엔드·프런트엔드 담당(석현), 에이전트 담당(새얼), 예측 엔진 담당(동환)과 이 코드를 처음 보는 사람.
- 파이썬·pandas는 알지만 이 프로젝트의 규칙(시점 규칙, 비율 목표 등)은 모릅니다.
</읽는 사람>

<프로젝트 사실>
아래 목록이 코드의 실제 구조입니다. 여기에 없는 파일·함수·변수·기능을 지어내지 마세요. 코드 파일이 함께 첨부되면 첨부한 코드를 우선하고, 아래 목록과 다른 점이 있으면 마지막에 따로 알려 주세요.

## 한 줄 소개
매장 POS 판매 기록 + 외부 신호(날씨·행사·학사일정) → 다음 날 메뉴별 판매량 범위(p10·p50·p90)와 준비량. LLM은 판매량 숫자를 만들지 않고 경고 문장만 쓴다.

## 폴더 구조 (저장소 naeil-myeotgae, 브랜치 ml-engine)
- `contracts/schemas.py` 팀 공통 데이터 형식(pydantic). `contracts/examples/` 예시 결과 파일
- `ml/ingest.py` POS 파일 → 판매 기록 / `ml/features.py` 모델 입력 표 / `ml/models.py` 모델 / `ml/evaluate.py` 검증 → backtest.json / `ml/predict.py` 내일 예측 → forecast.json / `ml/alerts.py` LLM 경고 / `ml/sample_data.py` 가상 매장 생성 / `ml/calendar_kr.py` 공휴일·가상 학사일정
- `ml/TASKS.md` 개발 명세, `ml/REVIEW.md` 판단·확인 목록과 진행 기록
- `run.py` 한 매장 전체 실행
- `tests/` 테스트 79개 (test_contracts, test_ingest, test_features, test_models, test_evaluate, test_backtest, test_predict, test_alerts, test_run, test_sample_data, fixtures/)
- `data/sample/sinchon-a/` 가상 매장 1년치 (sales.csv, signals.csv, store.json, truth.json=심어 둔 정답 효과)
- `data/raw/` 실제 매장 원본, `data/artifacts/{store_id}/` 실행 결과 → 둘 다 커밋하지 않음
- `frontend/` 석현(React), `agent/` 새얼(예정), `backend/` 석현(예정)

## 실행 흐름 (run.py: ingest → evaluate → predict, `--from-step`으로 중간부터)
- 입력: POS 엑셀·CSV(토스·OKPOS), `signals.json`(새얼, SignalRow 목록), `collection.json`(새얼, 행사·뉴스 원문, 선택), `store.json`(매장 설정)
- ingest: `ingest_store` → `sales_clean.csv`, `ingest_log.json`, `menu_merge_candidates.json`, (영수증 단위면) `sale_times.csv` / `_import_signals` → `signals.csv`
- evaluate: `run_backtest` → `backtest.json`
- predict: `predict_from_backtest` → (collection.json이 있으면) `make_warnings` → `forecast.json` → backend → 화면
- 명령: `python run.py --store sinchon-a --demo`(가상, 약 40초) / `python run.py --store seongsu-a --pos data/raw/x.xlsx --signals data/raw/x_signals.json` / `python -m pytest -q`(약 1분)
- run.py 옵션: --store, --demo, --demo-days, --pos, --pos-type(auto·toss·okpos), --signals, --close-time, --from-step, --iterations

## 꼭 지켜야 할 규칙
1. 시점 규칙: D일 예측은 D−1일 영업 종료 시각(`issue_time`)에 낸다. 판매 이력은 `shift(1)` 뒤 계산, 신호는 `published_at ≤ issue_time`인 것 중 가장 늦게 공개된 값. 누수 테스트 2개(test_features)가 지킨다.
2. 비율 목표: 모델은 판매량이 아니라 `qty / base_level`을 배운다. base_level = mean_28 → mean_7 → lag_1 중 처음 값, 최소 1. 예측 = 비율 × base_level.
3. 품절일(정답이 수요의 하한)과 메뉴 첫날(base 없음)은 학습·채점에서 뺀다.
4. 신호 채택: 자료가 있는 신호 묶음의 모든 조합을 같은 검증 구간에서 비교. M1(신호 없음)보다 전체 WAPE가 낮고 검증 구간 과반에서 나은 조합 중 WAPE가 가장 낮은 것.
5. 최종 테스트는 모든 결정이 끝난 뒤 한 번만. 결과를 보고 고치지 않는다.
6. LLM은 판매량 숫자를 만들거나 바꾸지 않는다. 경고의 인용문은 코드가 원문과 대조한다.

## 모듈·함수 (파이프라인 순서)
### ingest.py — POS 파일 → SalesRow 표
- `read_pos(path, pos_type="auto") -> (표, 기록)`: 위 10줄에서 머리글을 찾고(COLUMN_MAP), 합계·빈 행·음수(취소) 행을 빼고, 영수증 단위면 날짜×메뉴로 합산
- `suggest_menu_merges(menus)`: 이름이 비슷한 메뉴 쌍 '후보'만 (자모 유사도 ≥ 0.75, ICE/HOT은 다른 메뉴, 이름 속 숫자가 다르면 제외). 합치기는 사람이 `menu_map.json`에 승인
- `clean_sales(pos, store_id, menu_map)`: 메뉴명 통일 → 0개 판매 채우기 → 전 메뉴 0인 날(휴무) 제외 → 품절 표시 → 단종(14일 미판매) 기록
- `sold_out_evidence(qty)` / `mark_sold_out(sales)`: 판매량이 최댓값에 쌓이면 품절로 추정 (3번 이상, 10개 이상, 바로 아래 값들의 3배 이상)
- `temp_tag(name)`: 메뉴 이름의 'ICE'/'HOT'/'-'
- `ingest_store(pos_path, store_id, out, pos_type)`: 위를 한 번에, 결과 파일 저장
- 상수: COLUMN_MAP, SOLD_OUT_MIN_REPEATS=3, SOLD_OUT_MIN_QTY=10, SOLD_OUT_PILE_RATIO=3.0, DISCONTINUED_DAYS=14, MERGE_THRESHOLD=0.75

### features.py — 모델 입력 표
- `issue_time(date, close_time)`: 예측 시각 = D−1일 + 영업 종료 시각 (05시 전 마감은 23:59로)
- `build_frame(sales, signals, signal_names, predict_dates, close_time)`: 학습 행 + 예측 행(qty=NaN). 메뉴별 이력 → 매장 흐름 → 달력 → 신호 → 파생 신호
- `base_level(frame)`: 평소 수준 (위 규칙 2)
- `attach_signals(...)`: 시점 규칙으로 거른 신호를 세로형 → 가로형으로 붙임. kind가 calendar·event면 빈 날 0, forecast·observed면 NaN
- `add_derived(frame)` + `DERIVED_SIGNALS`: 파생 신호 = 오늘 값 − 이전 28일 평균 (`temp_diff`, `exam_period_diff`, `vacation_diff`, `festival_diff`)
- `feature_columns(model_name, frame, groups)`: 모델이 쓸 열 목록
- `load_sales(path)`, `load_signals(path)`: 신호는 .csv·.json 모두, 시간대 붙은 시각은 한국 시간으로
- 상수: HISTORY_FEATURES, CALENDAR_FEATURES, CATEGORICAL_FEATURES, BASE_FEATURES, SIGNAL_GROUPS, FEATURE_SETS, DEFAULT_CLOSE_TIME="21:00", ZERO_FILL_KINDS

### models.py — 모델
- `BaselineM0`: 지난주 같은 요일(lag_7 → 4주 같은 요일 평균 → 최근 7일 평균). 범위 = 4주 같은 요일 최소~최대
- `CatBoostQuantile(name, groups, iterations, depth, learning_rate=0.1, random_seed=0, short, n_seeds=3)`: 여섯 분위(p10·p40·p50·p60·p80·p90)를 한 모델로(MultiQuantile), 시드 3개 평균. 기본 150회·깊이 4, 짧은 데이터(학습 120일 미만) 100회·깊이 4
- `make_model(name)`: "M0" → BaselineM0, 그 외 → CatBoostQuantile
- 상수: QUANTILES, Q_COLS, SHORT_DATA_DAYS=120

### evaluate.py — 검증 → backtest.json
- 지표: `wape`(Σ|실제−예측|/Σ실제, 메인), `mae`, `bias`, `pinball`, `coverage`(실제가 [p10, p90] 안에 든 비율)
- `plan_folds(dates) -> FoldPlan`: 보통 = 검증 28일×4구간 + 최종 테스트 28일, 짧은 데이터 = 검증 7일×2구간 + 테스트 7일
- `cross_val_predict(frame, model_name, folds)`: 구간마다 그 전 데이터로만 학습해 구간을 예측 (시간순 교차검증)
- `beats(after, before)`, `pick_combo(scores)`, `decide(...)`, `model_label(groups)`: 신호 조합 선택과 이유 문장 (규칙 4)
- `check_calibration` / `fit_calibration` / `apply_calibration`: 예측 범위 보정 (앞 구간 오차로 이동량을 정해 다음 구간에서 나아지면 채택)
- `bootstrap_wape_change(base, other)`: M0 대비 오차 변화의 95% 구간 (7일 묶음 부트스트랩)
- `run_backtest(sales, signals, close_time) -> BacktestResult`: ① 조합 선택 ② 비교표(M0·M1·M2·M3) ③ 범위 보정 ④ 최종 테스트 1회 ⑤ data_note
- 모델 이름 규칙: 채택 없음 = M1, 날씨만 = M2, 그 외 하나라도 = M3

### predict.py — 내일 예측 → forecast.json
- `predict_next_day(sales, signals, groups, model_name, calibration, close_time, prep_mode, target_date, menus)`: 전체 기록으로 다시 학습해 다음 날 예측
- 근거(반사실): 채택된 신호 하나를 '평소 값'으로 바꿔 다시 예측한 p50과 비교, |효과| ≥ 3%만 문장으로 (`reason_text`, `usual_values`, `signal_sources`). 원재료와 파생 신호(vacation ↔ vacation_diff)는 함께 바꿈
- `prep_qty(q, mode)`: 준비 방식의 분위를 올림 (`PREP_MODES` = 폐기 줄이기 p40 · 균형 p50 · 품절 줄이기 p80)
- `predict_from_backtest(...)`, `write_forecast(...)`
- 상수: PREP_MODES, REASON_MIN_PCT=3.0, ZERO_USUAL, EVENT_TEXT

### alerts.py — LLM 특수 상황 경고 (숫자는 안 바꿈)
- `make_warnings(forecast, collection, cache_dir) -> list[Warning]`: 예측 날짜 ±1일 원문만 골라(`_payload`) LLM에 넘기고, 인용문이 원문에 글자 그대로 없으면 버림(`_quotes_are_real`). 입력 해시로 캐시
- 설정과 LLM 호출은 `ml/llm.py`: `settings()`(환경 변수 > .env > 기본값: LLM_PROVIDER, LLM_MODEL, API 키), `ask(system, user, schema, cache_dir)`(정해진 형식으로 답 받기 + 같은 입력은 저장된 답 사용)
- `PROVIDERS`: 제공자 이름 → 호출 함수. 기본 anthropic(`messages.parse`로 Warning 형식 강제)
- 아직 실제 API로 호출해 본 적 없음

### run.py — 한 매장 전체 실행
- `step_ingest`, `step_evaluate`, `step_predict`, `STEP_FUNCS`, `parse_args`, `main`
- `_import_signals(path, store_id, out)`: 신호 파일을 SignalRow로 검사하고 이 매장 줄만 저장
- `_need(path, step)`: 앞 단계 파일이 없으면 어느 단계부터 실행할지 알려 주고 멈춤

### 보조
- `sample_data.generate()`: 효과를 심어 둔 가상 매장 1년치 생성 (정답은 truth.json)
- `calendar_kr`: HOLIDAYS(실제 공휴일), CLOSED, `period_of(d)`(가상 학사일정)

## 데이터 구조
### 계약 (contracts/schemas.py, 바꾸면 팀 공유)
- SalesRow: date, store_id, menu, qty(≥0), sold_out — ingest가 만들고 ml이 읽음
- SignalRow: date, store_id, signal, value, source_url, published_at(KST), kind(observed·forecast·calendar·event) — agent가 만들고 features가 읽음
- Forecast: store_id, generated_at, rows[ForecastRow], signals_used, warnings[Warning] — predict가 만들고 backend가 읽음
  - ForecastRow: date, menu, pred(=p50), p10, p90, prep_qty, model, reasons[Reason] (p10 ≤ pred ≤ p90 검사)
  - Reason: signal, effect_pct, text, source_url
  - Warning: date, menu_scope(전체면 ["*"]), situation_type(유행급변·대형행사·기상특보·휴무가능성·데이터이상), direction(증가·감소·불확실), strength(낮음·중간·높음), evidence[Evidence(source_url, quote)], message
- BacktestResult: store_id, generated_at, folds, test_period(짧으면 None), cv_scores[ModelScore], decisions[SignalDecision], chosen_model, test_scores, data_note, calibration
  - ModelScore: model, wape, mae, bias, pinball_p10, pinball_p90, coverage_80, n, wape_by_fold
  - SignalDecision: signal_group, signals, adopted, wape_change_pct, folds_improved, folds_total, reason
  - Calibration: method, adopted, folds_improved, folds_total, reason, n_rows, shifts, test_coverage_before/after, test_below_before/after

### 모델 입력 표 (build_frame 결과, 한 행 = 매장·날짜·메뉴)
- 키·정답: store_id, date, menu, qty(예측 행은 NaN), sold_out
- 범주: store_id, menu, menu_temp(ICE·HOT·-)
- 달력: dow, is_weekend, is_holiday
- 판매 이력: lag_1, lag_7, lag_14, same_wd_mean_4, same_wd_min_4, same_wd_max_4, mean_7, mean_28, sold_out_7, days_since_start
- 비율 이력(÷ base_level): r_lag_1, r_lag_7, r_mean_7, r_same_wd
- 매장 흐름: store_7_28(최근 7일 ÷ 28일), store_lag1_28(어제 ÷ 28일)
- 신호 묶음(SIGNAL_GROUPS): weather = temp_diff, rain_mm / events = exam_period, vacation, festival, nearby_event, *_diff / trend = trend_level, trend_slope / special = special_day
- 모델별: M0 = 지난주 같은 요일, M1 = 신호 없음, M2 = + weather, M3 = + 나머지 묶음

### 설정·결과 파일 (data/artifacts/{store_id}/)
- 사람이 쓰는 것: store.json(store_id, close_time, prep_mode, 선택 menus), menu_map.json({"옛 이름": "새 이름"}), .env(API 키, 루트)
- 코드가 쓰는 것: sales_clean.csv, signals.csv, ingest_log.json, menu_merge_candidates.json, sale_times.csv, backtest.json, forecast.json, llm_cache/

### 늘릴 때 고칠 곳
새 외부 신호 → SIGNAL_GROUPS / 새 파생 신호 → DERIVED_SIGNALS / 새 POS 열 이름 → COLUMN_MAP / LLM 제공자 → PROVIDERS·.env / 근거 문장 → reason_text·EVENT_TEXT / 준비 방식 → PREP_MODES / 메뉴 통일·단종 → menu_map.json·store.json의 menus

## 현재 성능 (WAPE, 낮을수록 좋음 / 80% 범위 적중 = 실제가 [p10, p90] 안에 든 비율, 목표 0.80)
- 가상 매장 1년: M3 검증 0.218 · 테스트 0.191 (M0 0.338 · 0.297), 범위 적중 0.76
- 프랑스 빵집 실데이터 600일(신호 없음): M1 검증 0.299 · 테스트 0.300 (M0 0.408 · 0.412), 범위 적중 0.75
- 한계: 빵집 테스트 구간은 한 번 본 뒤 고침 / 짧은 데이터는 신호 채택이 흔들림 / LLM 경고는 실제 API 미호출
</프로젝트 사실>

<세 장 구성>
- 1장 "전체 그림": 한 줄 소개 → 폴더 구조(트리 그림) → 실행 흐름도(입력 파일 → 단계별 함수 → 출력 파일을 상자와 화살표로) → 실행 명령 → 꼭 지켜야 할 규칙 6개
- 2장 "모듈과 함수": 모듈마다 카드 하나 (파이프라인 순서로). 카드 안: 한 줄 역할 → 주요 함수(이름·인자 요약·한 줄 설명) → 주요 상수. `_`로 시작하는 내부 함수는 꼭 필요한 것만 작게
- 3장 "데이터 구조": 계약 클래스(필드 표) → 모델 입력 표의 열 구성(묶음별로 색 구분) → 설정·결과 파일 → 늘릴 때 고칠 곳 → 현재 성능과 한계
- 각 장 맨 위에 "이 장에서 알 수 있는 것" 한 줄, 맨 아래에 "n / 3" 쪽 번호
</세 장 구성>

<가독성 기준>
- 본문 9pt 이상, 코드·함수 이름 8.5pt 이상 고정폭 글꼴. 9pt 아래로 줄여서 맞추지 말고, 넘치면 설명을 줄이세요.
- 문단을 쓰지 말고 표·카드·짧은 항목으로. 한 항목은 두 줄을 넘기지 않습니다.
- 파이프라인 단계마다 색을 하나씩 정해(입력 / ingest / features / models / evaluate / predict / alerts) 세 장 모두에서 같은 색으로 씁니다. 흐름도의 상자 색과 2장 카드 색, 3장의 관련 항목 색이 같으면 장을 넘겨도 찾기 쉽습니다.
- 함수·변수·파일 이름은 코드 그대로 쓰고, 설명은 쉬운 한국어로 씁니다.
- 규칙 6개와 "현재 성능의 한계"는 눈에 띄게(배경색 상자) 둡니다.
</가독성 기준>

<기술 조건>
- HTML 파일 하나에 CSS를 모두 넣습니다. 외부 이미지·스크립트는 쓰지 않습니다. 본문 글꼴은 Pretendard(CDN), 안 되면 "Malgun Gothic", sans-serif. 고정폭은 "JetBrains Mono"(CDN) 또는 Consolas.
- `@page { size: A4; margin: 11mm; }`. 각 장을 `<section class="page">`로 나누고 `break-after: page`를 걸어, 인쇄하면 **정확히 세 장**이 되게 합니다.
- 흐름도와 아이콘은 인라인 SVG 또는 CSS 상자로 그립니다. 이모지는 쓰지 않습니다.
- `-webkit-print-color-adjust: exact; print-color-adjust: exact;`를 넣습니다.
</기술 조건>

<마무리 확인>
답을 주기 전에 확인하고 고치세요.
1. <프로젝트 사실>에 없는 파일·함수·변수·수치가 들어가지 않았는가
2. 인쇄하면 정확히 세 장이고, 본문이 9pt 이상인가
3. "vacation_diff는 어디서 만들어지나?", "forecast.json의 reasons는 어느 함수가 만드나?", "새 신호를 추가하려면 어디를 고치나?"를 이 문서만으로 30초 안에 찾을 수 있는가
결과를 HTML 아래에 세 줄 이내로 적어 주세요.
</마무리 확인>
