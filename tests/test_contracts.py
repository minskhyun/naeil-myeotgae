"""데이터 형식(contracts/schemas.py)이 '받아야 할 것은 받고, 막아야 할 것은 막는지' 확인한다."""
import datetime as dt
from pathlib import Path

import pytest
from pydantic import ValidationError

from contracts.schemas import (BacktestResult, Evidence, Forecast, ForecastRow, ModelScore, Reason,
                               SalesRow, SignalDecision, SignalRow, SourceReport, Warning)


def test_sales_row_accepts_valid_and_rejects_negative_qty():
    row = SalesRow(date="2026-11-18", store_id="seongsu-a", menu="소금빵", qty=42)
    assert row.date == dt.date(2026, 11, 18)       # 문자열 날짜가 date 타입으로 바뀜
    assert row.sold_out is False                   # 기본값
    with pytest.raises(ValidationError):
        SalesRow(date="2026-11-18", store_id="seongsu-a", menu="소금빵", qty=-1)


def test_signal_row_requires_known_kind_and_published_at():
    ok = SignalRow(date="2026-11-19", store_id="seongsu-a", signal="rain_mm", value=12.0,
                   source_url="https://www.kma.go.kr", published_at="2026-11-18T17:00:00", kind="forecast")
    assert ok.published_at == dt.datetime(2026, 11, 18, 17, 0)
    assert ok.menu is None                         # 메뉴 칸이 없으면 매장 전체 신호
    assert SignalRow(**{**ok.model_dump(), "menu": float("nan")}).menu is None    # 표를 거치며 NaN이 된 빈 칸
    assert SignalRow(**{**ok.model_dump(), "signal": "trend_level", "menu": "소금빵"}).menu == "소금빵"
    with pytest.raises(ValidationError):           # 정해진 4종류 밖의 kind
        SignalRow(**{**ok.model_dump(), "kind": "rumor"})
    with pytest.raises(ValidationError):           # published_at 빠짐
        SignalRow(**{k: v for k, v in ok.model_dump().items() if k != "published_at"})


def test_forecast_row_rejects_crossed_quantiles():
    with pytest.raises(ValidationError):
        ForecastRow(date="2026-11-19", menu="소금빵", pred=50, p10=60, p90=70, model="M1")


def test_warning_needs_at_least_one_quoted_evidence():
    base = dict(date="2026-11-19", menu_scope=["*"], situation_type="대형행사", direction="증가",
                strength="중간", message="근처 공연으로 손님이 늘 수 있어요.")
    with pytest.raises(ValidationError):           # 근거 0개
        Warning(**base, evidence=[])
    with pytest.raises(ValidationError):           # 인용문이 빈 문자열
        Warning(**base, evidence=[Evidence(source_url="https://x", quote="")])


def test_forecast_json_round_trip():
    fc = Forecast(
        store_id="sinchon-a", generated_at="2026-11-18T21:05:00",
        rows=[ForecastRow(date="2026-11-19", menu="소금빵", pred=55, p10=44, p90=68, prep_qty=60, model="M2",
                          reasons=[Reason(signal="rain_mm", effect_pct=-13.0, text="비 예보(12mm)로 평소보다 약 13% 적게 예상")])],
        signals_used=["temp_mean", "rain_mm"],
    )
    again = Forecast.model_validate_json(fc.model_dump_json())   # 저장 → 다시 읽기
    assert again == fc
    assert again.warnings == []


def test_backtest_result_round_trip_and_short_data_without_test_period():
    score = ModelScore(model="M0", wape=0.21, mae=6.3, bias=0.02, pinball_p10=1.1, pinball_p90=1.4,
                       coverage_80=0.74, n=140, wape_by_fold=[0.20, 0.22])
    bt = BacktestResult(
        store_id="seongsu-a", generated_at="2026-11-18T21:00:00",
        folds=[("2026-10-29", "2026-11-04"), ("2026-11-05", "2026-11-11")],
        test_period=None,                          # 짧은 데이터 모드: 최종 테스트 없음
        cv_scores=[score],
        decisions=[SignalDecision(signal_group="weather", signals=["temp_mean", "rain_mm"], adopted=False,
                                  wape_change_pct=1.5, folds_improved=1, folds_total=2,
                                  reason="날씨는 이 매장 판매 예측을 개선하지 못해 쓰지 않음 (2개 구간 중 1개만 개선)")],
        chosen_model="M1", test_scores=[], data_note="판매 기록 30일. 검증 구간이 짧아 결과의 변동이 큼",
    )
    again = BacktestResult.model_validate_json(bt.model_dump_json())
    assert again == bt
    assert again.folds[0] == (dt.date(2026, 10, 29), dt.date(2026, 11, 4))   # JSON 배열 → (date, date) 튜플


def test_signal_decision_rejects_impossible_fold_counts():
    with pytest.raises(ValidationError):
        SignalDecision(signal_group="weather", signals=[], adopted=True, wape_change_pct=-3,
                       folds_improved=5, folds_total=4, reason="-")


# ---------------------------------------------------------------- contracts/examples (팀원이 보고 개발하는 예시)

EXAMPLES = Path(__file__).resolve().parents[1] / "contracts" / "examples"


def test_examples_follow_contracts():
    import pandas as pd
    for rec in pd.read_csv(EXAMPLES / "sales.csv").to_dict("records"):
        SalesRow.model_validate(rec)
    for rec in pd.read_csv(EXAMPLES / "signals.csv").to_dict("records"):
        SignalRow.model_validate(rec)
    BacktestResult.model_validate_json((EXAMPLES / "backtest.json").read_text(encoding="utf-8"))
    Forecast.model_validate_json((EXAMPLES / "forecast.json").read_text(encoding="utf-8"))
    report = SourceReport.model_validate_json((EXAMPLES / "sources_report.json").read_text(encoding="utf-8"))
    assert report.plan and report.signals and report.articles


# ---------------------------------------------------------------- 매장 설정 (store.json)

def test_store_config_defaults_and_keeps_unknown_fields(tmp_path):
    """store.json은 사람이 직접 고칠 수 있다: 빠진 칸은 기본값, 모르는 칸은 다시 저장해도 그대로 남는다."""
    import json
    from contracts.schemas import StoreConfig
    path = tmp_path / "store.json"
    path.write_text('{"store_id": "s", "memo": "사장님 메모"}', encoding="utf-8")
    store = StoreConfig.read(path)
    assert (store.close_time, store.prep_mode, store.menus, store.lat) == ("21:00", "균형", None, None)
    store.prep_mode = "품절 줄이기"
    store.write(path)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["memo"] == "사장님 메모" and saved["prep_mode"] == "품절 줄이기" and "lat" not in saved
