"""내일 예측 + 근거 문장 + 준비량 → forecast.json

순서 (predict_next_day)
  1) backtest.json에서 채택된 신호 묶음·모델·범위 보정을 읽는다 (evaluate.py가 정한 것을 그대로 따름)
  2) 전체 판매 기록(최종 테스트 기간 포함)으로 다시 학습
  3) 마지막 판매일 다음 날을 예측 (issue_time 시점 규칙은 features.py가 그대로 지킴)
  4) 근거(반사실 방식): 신호 하나를 '평소 값'으로 바꿔 다시 예측 → 차이가 3% 이상이면 문장으로
  5) 준비량: 사장님이 고른 방식의 분위를 올림

고치기 쉬운 곳
  - 준비 방식과 분위: PREP_MODES
  - 근거 문장: reason_text, EVENT_TEXT (LLM을 쓰지 않는 고정 문장). 새 신호의 '평소 값'은 FIXED_USUAL
"""
import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

from contracts.schemas import DEFAULT_PREP_MODE, BacktestResult, Forecast, ForecastRow, Reason, SalesHistory
from ml.calibration import apply_calibration
from ml.features import (DEFAULT_CLOSE_TIME, DERIVED_SIGNALS, SPECIAL_LEAD_DAYS, ZERO_FILL_KINDS, available_signals,
                         base_level, build_frame, issue_time)
from ml.models import make_model
from ml.paths import ARTIFACTS

# 준비 방식 → 준비량으로 쓸 값. 균형 = 예상 판매량(평균). 중앙값(p50)을 쓰면 조금씩 팔리는 메뉴가 모두 0이 된다 (models.py)
PREP_MODES = {"폐기 줄이기": "p40", "균형": "pred", "품절 줄이기": "p80"}
REASON_MIN_PCT = 3.0        # 효과가 이보다 작으면 근거로 보여 주지 않는다
RECENT_DAYS = 28            # 연속값 신호의 '평소 값' = 최근 28일 중앙값
# 평소 값이 정해져 있는 신호: 비 안 옴(0), 최근 평균과 같은 기온(0), 평소와 같은 검색량(1배)
FIXED_USUAL = {"rain_mm": 0.0, "temp_diff": 0.0, "trend_level": 1.0}
EVENT_TEXT = {"exam_period": "시험기간이라", "vacation": "방학 기간이라",
              "festival": "축제 기간이라", "nearby_event": "근처 행사가 있어", "special_day": "기념일이라",
              "event_impact": "이 메뉴와 관련 있는 근처 행사가 있어", "special_impact": "이 메뉴와 관련 있는 기념일이 가까워"}


# ---------------------------------------------------------------- 준비량

def prep_qty(q: pd.DataFrame, mode: str = DEFAULT_PREP_MODE) -> pd.Series:
    """준비량 = 고른 방식의 값을 올림한 정수.  폐기 줄이기=p40, 균형=예상 판매량(pred), 품절 줄이기=p80.
    폐기 줄이기 ≤ 균형 ≤ 품절 줄이기 순서는 지킨다 (조금씩 팔리는 메뉴는 평균이 p80보다 클 수도, p40이 평균보다 클 수도 있다)."""
    if mode not in PREP_MODES:
        raise ValueError(f"준비 방식은 {list(PREP_MODES)} 중 하나여야 합니다: {mode!r}")
    level = {"폐기 줄이기": np.minimum(q["p40"], q["pred"]), "균형": q["pred"], "품절 줄이기": np.maximum(q["p80"], q["pred"])}[mode]
    # round(…, 6): 40.0000001 같은 계산 찌꺼기가 41로 올림되지 않게
    return np.ceil(level.round(6)).astype(int)


# ---------------------------------------------------------------- 근거 문장

def reason_text(signal: str, value: float, pct: float) -> str:
    """근거 한 줄 (템플릿, LLM 사용 안 함).  value = 내일 그 신호의 값, pct = 그 때문에 달라진 정도(%)."""
    tail = f"평소보다 약 {abs(pct):.0f}% {'많이' if pct > 0 else '적게'} 예상"
    if signal == "rain_mm":
        head = f"비 예보({value:g}mm)로"
    elif signal == "temp_diff":
        head = f"기온이 최근 평균보다 {abs(value):.0f}도 {'높아' if value > 0 else '낮아'}"
    elif signal == "special_lead":                       # 값 7 = 하루 전, 1 = 일주일 전
        head = f"기념일을 {SPECIAL_LEAD_DAYS + 1 - round(value)}일 앞두고 있어"
    elif signal == "trend_level":
        head = f"이 메뉴 검색량이 그 전 4주보다 {abs(value - 1) * 100:.0f}% {'늘어' if value > 1 else '줄어'}"
    elif signal in EVENT_TEXT:
        head = EVENT_TEXT[signal]
    else:
        head = f"{signal} 신호({value:g})로"
    return f"{head} {tail}"


def usual_values(train: pd.DataFrame, signal_cols: list[str], kinds: dict[str, set]) -> dict[str, float]:
    """신호마다 '평소 값'.  FIXED_USUAL에 있으면 그 값, 학사일정·행사 = 0 (없는 날이 평소), 그 밖의 연속값 = 최근 28일 중앙값."""
    recent = train[train["date"] > train["date"].max() - pd.Timedelta(days=RECENT_DAYS)].drop_duplicates("date")
    usual = {}
    for c in signal_cols:
        if c in FIXED_USUAL:
            usual[c] = FIXED_USUAL[c]
        elif kinds.get(c, set()) <= ZERO_FILL_KINDS:
            usual[c] = 0.0
        else:
            usual[c] = round(float(recent[c].median()), 1)
    return usual


def signal_sources(signals: pd.DataFrame, store_id: str, date, close_time: str) -> dict[str, str]:
    """그 날짜에 실제로 쓴 발표본(issue_time까지 공개된 것 중 가장 늦은 것)의 출처 주소."""
    s = signals[(signals["store_id"] == store_id) & (signals["date"] == date)
                & (signals["published_at"] <= issue_time(date, close_time))]
    return s.sort_values("published_at").groupby("signal")["source_url"].last().to_dict()


def explain(model, rows: pd.DataFrame, p50: pd.Series, usual: dict[str, float],
            sources: dict[str, str]) -> list[list[Reason]]:
    """메뉴(행)마다 근거 목록.  반사실 방식: 신호 하나를 '평소 값'으로 바꿔 다시 예측한 p50과 실제 예측을 비교한다.

    원재료도 모델 변수인 파생 신호(예: vacation → vacation_diff)는 따로 근거를 내지 않고 원재료와 함께 바꾼다.
    원재료가 평소 값이었다면 파생값(오늘 − 최근 평균)도 그만큼 달라진다: diff + (평소 값 − 오늘 값)
    """
    linked = {s: [d for d, (src, _) in DERIVED_SIGNALS.items() if src == s and d in model.signal_cols]
              for s in model.signal_cols}
    folded = {d for ds in linked.values() for d in ds}
    reasons = [[] for _ in range(len(rows))]
    for sig in model.signal_cols:
        value = rows[sig]
        if sig in folded or value.isna().all() or (value == usual[sig]).all():   # 자료가 없거나 이미 평소 값
            continue
        cf_rows = rows.assign(**{sig: usual[sig]}, **{d: rows[d] + (usual[sig] - value) for d in linked[sig]})
        cf = model.predict(cf_rows)["p50"]                                      # '평소였다면'의 예측
        pct = (p50 - cf) / cf.where(cf > 0) * 100
        for i in range(len(rows)):
            if pd.notna(pct[i]) and pd.notna(value[i]) and abs(pct[i]) >= REASON_MIN_PCT:
                reasons[i].append(Reason(signal=sig, effect_pct=round(float(pct[i]), 1),
                                         text=reason_text(sig, float(value[i]), float(pct[i])),
                                         source_url=sources.get(sig)))
    return [sorted(r, key=lambda x: -abs(x.effect_pct)) for r in reasons]       # 효과가 큰 것부터


# ---------------------------------------------------------------- 최근 판매 (화면 그래프용)

HISTORY_DAYS = 28            # 준비표 그래프에 보여 줄 날 수 (4주 = 같은 요일이 네 번)


def recent_history(sales: pd.DataFrame, menus: list[str], days: int = HISTORY_DAYS) -> SalesHistory:
    """마지막 판매일까지 최근 days일의 실제 판매: 하루 전체 합계 + menus의 메뉴별 판매량.
    예측에는 쓰지 않는다. 화면이 '최근 4주와 내일 예상'을 나란히 그릴 때 쓴다. 기록이 없는 날(휴무)은 None."""
    sales = sales.assign(date=pd.to_datetime(sales["date"]))
    dates = pd.date_range(end=sales["date"].max(), periods=days)
    total = sales.groupby("date")["qty"].sum().reindex(dates)
    wide = sales[sales["menu"].isin(menus)].pivot_table(index="date", columns="menu", values="qty", aggfunc="sum").reindex(dates)
    clean = lambda s: [None if pd.isna(v) else float(v) for v in s]      # noqa: E731
    return SalesHistory(dates=[d.date() for d in dates], total=clean(total),
                        menus={m: clean(wide[m]) for m in menus if m in wide})


# ---------------------------------------------------------------- 내일 예측

def predict_next_day(sales: pd.DataFrame, signals: pd.DataFrame | None, groups: list[str], model_name: str,
                     calibration: dict[str, float] | None = None, close_time: str = DEFAULT_CLOSE_TIME,
                     prep_mode: str = DEFAULT_PREP_MODE, target_date=None, menus: list[str] | None = None,
                     **model_kwargs) -> Forecast:
    """판매 기록 + 신호 → 다음 날(또는 target_date) Forecast.

    groups       채택된 신호 묶음 (예: ["weather", "events"])
    model_name   backtest의 chosen_model ("M1"~"M3")
    calibration  채택된 범위 보정 이동량 (없으면 None)
    menus        지금 파는 메뉴 목록 (store.json의 "menus"). 있으면 이 메뉴만 예측 (단종 메뉴 제외).
                 없으면 최근 14일 안에 팔린 메뉴를 모두 예측. 학습에는 단종 메뉴 기록도 그대로 쓴다.
    """
    store_id = str(sales["store_id"].iloc[0])
    if sales["store_id"].nunique() != 1:
        raise ValueError("매장 하나씩 예측합니다.")
    sales = sales.assign(date=pd.to_datetime(sales["date"]))
    target = pd.Timestamp(target_date) if target_date is not None else sales["date"].max() + pd.Timedelta(days=1)

    names, kinds = [], {}
    if signals is not None and groups:
        signals = signals[signals["store_id"] == store_id]
        names = available_signals(groups, signals)
        kinds = signals.groupby("signal")["kind"].agg(set).to_dict()
    frame = build_frame(sales, signals if names else None, names, predict_dates=[target], close_time=close_time)

    train = frame[frame["qty"].notna()]
    rows = frame[(frame["date"] == target) & frame["qty"].isna()]
    if menus is not None:
        rows = rows[rows["menu"].isin(menus)]
    rows = rows.reset_index(drop=True)
    if rows.empty:
        raise ValueError(f"{target.date()}에 예측할 메뉴가 없습니다 (최근 14일 안에 팔린 메뉴가 없음).")

    # 전체 기록으로 다시 학습 → 예측 (+ 채택된 범위 보정)
    model = make_model(model_name, groups=groups, **model_kwargs).fit(train)
    q = model.predict(rows)
    if calibration:
        q = apply_calibration(q.assign(base=base_level(rows)), calibration)
        q["pred"] = q["pred"].clip(q["p10"], q["p90"])                # 보정으로 범위가 움직여도 예상 판매량은 범위 안에

    reasons = explain(model, rows, q["p50"], usual_values(train, model.signal_cols, kinds),
                      signal_sources(signals, store_id, target, close_time) if names else {})
    prep = prep_qty(q, prep_mode)
    by_mode = {mode: prep_qty(q, mode) for mode in PREP_MODES}       # 화면에서 준비 기준을 바꿔 볼 때 쓰는 값
    out_rows = [
        ForecastRow(date=target.date(), menu=rows.at[i, "menu"],
                    pred=round(float(q.at[i, "pred"]), 1), p10=round(float(q.at[i, "p10"]), 1),
                    p90=round(float(q.at[i, "p90"]), 1), prep_qty=int(prep[i]),
                    prep_by_mode={mode: int(v[i]) for mode, v in by_mode.items()}, model=model_name, reasons=reasons[i])
        for i in range(len(rows))
    ]
    return Forecast(store_id=store_id, generated_at=dt.datetime.now().replace(microsecond=0),
                    rows=out_rows, signals_used=list(model.signal_cols), warnings=[])


def predict_from_backtest(sales, signals, backtest: BacktestResult, **kwargs) -> Forecast:
    """backtest.json의 결정(채택 신호·모델·범위 보정)을 그대로 따라 예측한다."""
    groups = [d.signal_group for d in backtest.decisions if d.adopted]
    cal = backtest.calibration
    shifts = cal.shifts if cal is not None and cal.adopted else None
    return predict_next_day(sales, signals, groups, backtest.chosen_model, shifts, **kwargs)


def write_forecast(fc: Forecast, out_root: Path = ARTIFACTS) -> Path:
    path = Path(out_root) / fc.store_id / "forecast.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(fc.model_dump_json(indent=2), encoding="utf-8")
    return path
