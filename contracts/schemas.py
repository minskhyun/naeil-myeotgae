"""팀 공통 데이터 형식 (파트 사이에 주고받는 데이터의 '계약').

누가 쓰고 누가 읽나
- SalesRow        ml/ingest.py가 만듦 → ml 전체가 읽음
- SignalRow       agent/(새얼)가 만듦 → ml/features.py가 읽음
- Forecast        ml/predict.py가 만듦 → backend/(석현)가 읽어 화면에 보여 줌
- BacktestResult  ml/evaluate.py가 만듦 → 모델 비교 화면이 읽음

이 파일을 바꾸면 반드시 팀에 공유한다. 한쪽만 바꾸면 다른 쪽 코드가 깨진다.

※ 로컬 개발용으로 다시 만든 버전이다. 기존 SalesRow·SignalRow·Reason·ForecastRow·Forecast는
  PROJECT_CONTEXT.md의 설명을 보고 복원했으므로, 팀 저장소의 원본과 필드가 다를 수 있다.
"""
import datetime as dt  # 'date'라는 필드 이름과 datetime.date 타입이 부딪히지 않게 모듈째로 가져온다
from typing import Literal

from pydantic import BaseModel, Field, model_validator

ModelName = Literal["M0", "M1", "M2", "M3"]


# ---------------------------------------------------------------- 입력: 판매·신호

class SalesRow(BaseModel):
    """정리된 판매 기록 한 줄 = (매장, 날짜, 메뉴) 하나."""
    date: dt.date
    store_id: str
    menu: str                                   # 통일된 메뉴명
    qty: int = Field(ge=0)                      # 판매 수량 (취소는 ingest에서 이미 상계)
    sold_out: bool = False                      # True면 qty는 수요의 하한 (검열된 수요)


class SignalRow(BaseModel):
    """외부 신호 한 줄 (세로형: 신호 하나당 한 행)."""
    date: dt.date                               # 신호가 '해당하는' 날짜 (예: 비가 오는 날)
    store_id: str
    signal: str                                 # 예: "rain_mm", "exam_period"
    value: float
    source_url: str
    published_at: dt.datetime                   # 이 값이 '공개된' 시각 → 미래 정보 누수 방지에 씀
    kind: Literal["observed", "forecast", "calendar", "event"]


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
    pred: float = Field(ge=0)                   # 예상 판매량 (= p50)
    p10: float = Field(ge=0)                    # 10%의 날은 이보다 적게 팔림
    p90: float = Field(ge=0)                    # 90%의 날은 이보다 적게 팔림
    prep_qty: int | None = Field(default=None, ge=0)   # 권장 준비량 (준비량 기능 전에는 None)
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
    """LLM이 만드는 특수 상황 경고. 숫자는 바꾸지 않고 '주의하라'는 말만 한다."""
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
    ※ TASKS.md에 없던 추가 형식. predict.py는 adopted=True일 때만 shifts를 적용한다."""
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
    calibration: Calibration | None = None      # 범위 보정 (TASKS.md에 없던 추가 필드, 없어도 됨)
