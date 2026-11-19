"""팀 공통 데이터 형식 (파트 사이에 주고받는 데이터의 '계약'). 파일 하나 = 클래스 하나.

    파일 (data/artifacts/{매장}/)   형식            만드는 곳                    읽는 곳
    store.json                     StoreConfig     run.py, 웹의 준비 기준 변경    run.py, 웹 API
    sales_clean.csv                SalesRow        ml/ingest.py                  ml 전체
    signals.csv                    SignalRow       agent/ (주변 정보 수집)        ml/features.py
    collection.json                CollectionItem  agent/ (행사·뉴스 원문)        ml/alerts.py
    sources_report.json            SourceReport    agent/report.py               웹 '주변 정보'
    backtest.json                  BacktestResult  ml/evaluate.py                웹 '얼마나 맞나'
    forecast.json                  Forecast        ml/predict.py + ml/alerts.py  웹 '내일 준비표'

이 파일을 바꾸면 화면(frontend/src/api.ts)의 타입과 contracts/examples/ 예시도 같이 고친다.
"""
import datetime as dt  # 'date'라는 필드 이름과 datetime.date 타입이 부딪히지 않게 모듈째로 가져온다
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ModelName = Literal["M0", "M1", "M2", "M3"]
DEFAULT_CLOSE_TIME = "21:00"
DEFAULT_PREP_MODE = "균형"


# ---------------------------------------------------------------- 매장 설정

class StoreConfig(BaseModel):
    """매장 하나의 설정 → store.json. 사람이 직접 열어 고쳐도 되는 파일이다 (모르는 칸은 지우지 않고 그대로 둔다)."""
    model_config = ConfigDict(extra="allow")

    store_id: str
    name: str | None = None                     # 화면에 보일 이름 (없으면 store_id)
    close_time: str = DEFAULT_CLOSE_TIME        # 영업 종료 시각 "HH:MM" → 이 시각까지 공개된 정보만 내일 예측에 씀
    prep_mode: str = DEFAULT_PREP_MODE          # 준비 기준: "폐기 줄이기" / "균형" / "품절 줄이기"
    address: str | None = None                  # 주소 → 위도·경도를 찾아 주변 정보를 모음
    lat: float | None = None
    lon: float | None = None
    category: str = "카페"                       # 업종 (정보원 선택 에이전트에게 알려 줌)
    menus: list[str] | None = None              # 지금 파는 메뉴 (없으면 최근 14일 안에 팔린 메뉴 전부)
    area_keywords: list[str] | None = None      # 뉴스 검색에 쓸 동네 이름 (없으면 주소에서 뽑음)

    @classmethod
    def read(cls, path) -> "StoreConfig":
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))

    def write(self, path) -> None:
        Path(path).write_text(self.model_dump_json(indent=1, exclude_none=True), encoding="utf-8")


# ---------------------------------------------------------------- 입력: 판매·신호

class SalesRow(BaseModel):
    """정리된 판매 기록 한 줄 = (매장, 날짜, 메뉴) 하나."""
    date: dt.date
    store_id: str
    menu: str                                   # 통일된 메뉴명
    qty: int = Field(ge=0)                      # 판매 수량 (취소는 ingest에서 이미 상계)
    sold_out: bool = False                      # True면 qty는 수요의 하한 (검열된 수요)


class SignalRow(BaseModel):
    """외부 신호 한 줄 (세로형: 신호 하나당 한 행). 신호 이름은 ml/features.py의 SIGNAL_GROUPS에 있는 것만 모델이 쓴다."""
    date: dt.date                               # 신호가 '해당하는' 날짜 (예: 비가 오는 날)
    store_id: str
    signal: str                                 # 예: "rain_mm", "exam_period"
    menu: str | None = None                     # 메뉴별 신호(예: 메뉴 검색량 trend_level)면 메뉴 이름, 매장 전체 신호면 비움
    value: float
    source_url: str
    published_at: dt.datetime                   # 이 값이 '공개된' 시각 → 미래 정보 누수 방지에 씀
    kind: Literal["observed", "forecast", "calendar", "event"]

    @field_validator("menu", mode="before")
    @classmethod
    def _blank_menu_means_whole_store(cls, v):
        """표(DataFrame·CSV)를 거치면 빈 칸이 NaN이나 ""로 바뀐다 → None(매장 전체 신호)으로 읽는다."""
        return None if v is None or v == "" or v != v else v      # v != v 는 NaN일 때만 참


class CollectionItem(BaseModel):
    """모은 원문 하나 (collection.json의 한 항목). AI 주의 안내의 재료이고, 모델 변수로는 쓰지 않는다."""
    date: dt.date                               # 이 자료가 해당하는 날 (예: 행사가 열리는 날)
    title: str
    text: str = Field(min_length=1)             # 원문 그대로 (요약하지 않음). 경고의 인용문을 이 글과 대조한다
    source_url: str
    published_at: dt.datetime | None = None     # 공개 시각(KST). 있으면 예측 시각 뒤에 나온 글은 쓰지 않는다


# ---------------------------------------------------------------- 출력: 주변 정보 수집 요약

class SignalSummary(BaseModel):
    """모은 신호 하나의 요약 (signals.csv를 신호 이름별로 묶은 것)."""
    signal: str
    n_days: int = Field(ge=0)                   # 값이 있는 날짜 수
    first_date: dt.date
    last_date: dt.date
    n_menus: int = Field(default=0, ge=0)       # 메뉴별 신호면 메뉴 수, 매장 전체 신호면 0
    source_url: str | None = None
    note: str | None = None                     # 밝혀야 할 점 (예: 관측값을 예보 대신 씀)


class ArticleSummary(BaseModel):
    """찾은 행사·뉴스 글 하나 (collection.json에서 본문을 뺀 것)."""
    title: str
    source_url: str
    first_date: dt.date                         # 이 글의 행사가 해당하는 첫날
    last_date: dt.date                          # 마지막 날
    published_at: dt.datetime | None = None


class SourceReport(BaseModel):
    """한 매장의 주변 정보를 어디서 왜 무엇을 모았는지 → sources_report.json"""
    store_id: str
    generated_at: dt.datetime
    plan: dict | None = None                    # 정보원 선택 에이전트의 결과 그대로 (형식: backend/collectors/agent.py)
    n_nearby: int | None = None                 # 에이전트가 살펴본 주변 시설 수
    signals: list[SignalSummary] = Field(default_factory=list)
    articles: list[ArticleSummary] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)   # 수집 기록 (무엇을 몇 건, 왜 건너뛰었는지)


# ---------------------------------------------------------------- 출력: 내일 예측

class Reason(BaseModel):
    """예측 근거 하나. 예: 비 예보로 약 13% 적게 예상."""
    signal: str
    effect_pct: float                           # 이 신호 때문에 달라진 정도 (%)
    text: str                                   # 사장님께 보여 줄 문장 (템플릿으로 생성)
    source_url: str | None = None


class ForecastRow(BaseModel):
    """메뉴 하나의 내일 예측."""
    date: dt.date
    menu: str
    pred: float = Field(ge=0)                   # 예상 판매량 (평균 기대값. 중앙값이 아니다 → ml/models.py)
    p10: float = Field(ge=0)                    # 10%의 날은 이보다 적게 팔림
    p90: float = Field(ge=0)                    # 90%의 날은 이보다 적게 팔림
    prep_qty: int | None = Field(default=None, ge=0)   # 권장 준비량
    model: ModelName
    reasons: list[Reason] = Field(default_factory=list)

    @model_validator(mode="after")
    def _quantiles_in_order(self):
        if not (self.p10 <= self.pred <= self.p90):
            raise ValueError(f"p10 ≤ pred ≤ p90 이어야 함: {self.p10}, {self.pred}, {self.p90}")
        return self


class Evidence(BaseModel):
    source_url: str
    quote: str = Field(min_length=1)            # 원문 인용. 없으면 경고 자체를 만들지 않는다


class Warning(BaseModel):  # noqa: A001  (파이썬 내장 Warning과 이름이 같음, TASKS.md 명세를 따름)
    """LLM이 만드는 특수 상황 경고 = 화면의 'AI 주의 안내'. 숫자는 바꾸지 않고 '주의하라'는 말만 한다."""
    date: dt.date
    menu_scope: list[str]                       # 영향 받는 메뉴, 전체면 ["*"]
    situation_type: Literal["유행급변", "대형행사", "기상특보", "휴무가능성", "데이터이상"]
    direction: Literal["증가", "감소", "불확실"]
    strength: Literal["낮음", "중간", "높음"]
    evidence: list[Evidence] = Field(min_length=1)
    message: str                                # 사장님께 보여 줄 한 문장


class Forecast(BaseModel):
    """한 매장의 내일 예측 전체 → forecast.json"""
    store_id: str
    generated_at: dt.datetime
    rows: list[ForecastRow]
    signals_used: list[str] = Field(default_factory=list)   # 이 매장에서 채택된 신호
    warnings: list[Warning] = Field(default_factory=list)


# ---------------------------------------------------------------- 출력: 모델 검증 결과

class ModelScore(BaseModel):
    model: str                                  # "M0", "M1", ...
    wape: float = Field(ge=0)                   # Σ|실제−예측| / Σ실제 (메인 지표)
    mae: float = Field(ge=0)                    # 하루 평균 몇 개 틀렸나
    bias: float                                 # Σ(예측−실제) / Σ실제, +면 많이 예측하는 경향
    pinball_p10: float = Field(ge=0)
    pinball_p90: float = Field(ge=0)
    coverage_80: float = Field(ge=0, le=1)      # 실제값이 [p10, p90] 안에 든 비율 (이상적으로 0.8)
    n: int = Field(ge=0)                        # 채점한 (날짜, 메뉴) 행 수
    wape_by_fold: list[float]                   # 검증 구간별 WAPE
    # 화면의 '남거나 모자란 개수' (11/19). 비율(wape)은 하루 한두 개 팔리는 메뉴에서 크게 튀어, 화면에는 개수로 보여 준다
    over: float = Field(default=0, ge=0)        # 예측대로 준비했다면 남았을 개수 합 Σmax(예측−실제, 0)
    under: float = Field(default=0, ge=0)       # 모자랐을 개수 합 Σmax(실제−예측, 0).  over + under = Σ|실제−예측|
    days: int = Field(default=0, ge=0)          # 채점한 날짜 수 (하루 평균을 낼 때 나누는 수)
    amount: float | None = None                 # 남거나 모자란 개수를 판매가로 환산한 금액 합(원). 판매가를 모르면 None


class SignalDecision(BaseModel):
    signal_group: str                           # "weather", "events", ...
    signals: list[str]
    adopted: bool
    wape_change_pct: float                      # 넣었을 때 WAPE 변화 (음수 = 개선)
    folds_improved: int = Field(ge=0)
    folds_total: int = Field(ge=0)
    reason: str                                 # 화면에 보여 줄 한 줄 (쉬운 한국어)

    @model_validator(mode="after")
    def _folds_consistent(self):
        if self.folds_improved > self.folds_total:
            raise ValueError("folds_improved는 folds_total보다 클 수 없음")
        return self


class Calibration(BaseModel):
    """범위 보정 (분위별 conformal 보정). 검증 구간의 예측 오차로 분위마다 '평소 수준 대비' 이동량을 정한다.
    신호처럼 검증으로 채택한다: 앞 구간들로 보정 → 다음 구간에 적용해 pinball이 과반에서 줄 때만 쓴다.
    predict.py는 adopted=True일 때만 shifts를 적용한다."""
    method: str                                 # "conformal-ratio"
    adopted: bool
    folds_improved: int = Field(ge=0)           # 검사한 구간 중 보정으로 pinball이 줄어든 수
    folds_total: int = Field(ge=0)              # 검사한 구간 수 (= 검증 구간 수 − 1)
    reason: str                                 # 쉬운 한국어 한 줄
    n_rows: int = Field(ge=0)                   # 이동량 계산에 쓴 (날짜, 메뉴) 행 수
    shifts: dict[str, float] = Field(default_factory=dict)   # 채택 시 {"p10": -0.12, ..., "p90": 0.08}
    test_coverage_before: float | None = None   # 최종 테스트에서 보정 전 [p10, p90] 적중률 (채택·테스트 있을 때만)
    test_coverage_after: float | None = None    # 보정 후
    test_below_before: dict[str, float] | None = None   # 최종 테스트에서 '실제 ≤ 분위 예측' 비율 (p80이면 0.8이 이상적)
    test_below_after: dict[str, float] | None = None


class SalesHistory(BaseModel):
    """준비표 그래프의 재료: 최근 며칠의 실제 판매 → history.json (ml/predict.py의 recent_history)"""
    dates: list[dt.date]                        # 예측 날짜 바로 전날까지, 오래된 날부터
    total: list[float | None]                   # 하루 전체 판매 개수 (휴무일은 None)
    menus: dict[str, list[float | None]]        # 메뉴별 하루 판매 개수 (휴무일·기록 없는 날은 None)


class BacktestResult(BaseModel):
    """한 매장의 모델 비교·신호 채택 결과 → backtest.json"""
    store_id: str
    generated_at: dt.datetime
    folds: list[tuple[dt.date, dt.date]]        # 검증 구간들 (시작일, 종료일)
    test_period: tuple[dt.date, dt.date] | None # 데이터가 너무 짧으면 최종 테스트 없음 → None
    cv_scores: list[ModelScore]                 # 검증 구간 평균
    decisions: list[SignalDecision]
    chosen_model: str
    test_scores: list[ModelScore]               # 최종 테스트 (M0 vs 채택 모델), 한 번만 계산
    data_note: str                              # 예: "판매 기록 34일. 검증 구간이 짧아 결과의 변동이 큼"
    calibration: Calibration | None = None      # 범위 보정 (없어도 됨)
