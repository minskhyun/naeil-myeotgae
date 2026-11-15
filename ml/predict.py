"""내일 예측 + 근거 문장 + 준비량 → forecast.json  (TASKS.md §9·§10)

순서
  1) backtest.json에서 채택된 신호 묶음·모델·범위 보정을 읽는다 (evaluate.py가 정한 것을 그대로 따름)
  2) 전체 판매 기록(최종 테스트 기간 포함)으로 다시 학습
  3) 마지막 판매일 다음 날을 예측 (issue_time 시점 규칙은 features.py가 그대로 지킴)
  4) 근거(반사실 방식): 신호 하나를 '평소 값'으로 바꿔 다시 예측 → 차이가 3% 이상이면 문장으로
  5) 준비량: 사장님이 고른 방식의 분위를 올림

실행:  python -m ml.predict [매장 폴더]      (먼저 python -m ml.evaluate 로 backtest.json을 만들어야 함)
       → data/artifacts/{store_id}/forecast.json
"""
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from contracts.schemas import BacktestResult, Forecast, ForecastRow, Reason
from ml.evaluate import ARTIFACTS, ROOT, apply_calibration
from ml.features import (DEFAULT_CLOSE_TIME, DERIVED_SIGNALS, ZERO_FILL_KINDS, available_signals, build_frame, issue_time,
                         load_sales, load_signals)
from ml.models import base_level, make_model

PREP_MODES = {"폐기 줄이기": "p60", "균형": "p50", "품절 줄이기": "p80"}
REASON_MIN_PCT = 3.0        # 효과가 이보다 작으면 근거로 보여 주지 않는다
RECENT_DAYS = 28            # 연속값 신호의 '평소 값' = 최근 28일 중앙값
ZERO_USUAL = {"rain_mm", "temp_diff"}   # 평소 값이 0인 신호 (비 안 옴, 최근 평균과 같은 기온)
EVENT_TEXT = {"exam_period": "시험기간이라", "vacation": "방학 기간이라",
              "festival": "축제 기간이라", "nearby_event": "근처 행사가 있어", "special_day": "기념일이라"}


# ---------------------------------------------------------------- 준비량

def prep_qty(q: pd.DataFrame, mode: str = "균형") -> pd.Series:
    """준비량 = 고른 방식의 분위를 올림한 정수.  폐기 줄이기=p60, 균형=p50, 품절 줄이기=p80."""
    if mode not in PREP_MODES:
        raise ValueError(f"준비 방식은 {list(PREP_MODES)} 중 하나여야 합니다: {mode!r}")
    # round(…, 6): 40.0000001 같은 계산 찌꺼기가 41로 올림되지 않게
    return np.ceil(q[PREP_MODES[mode]].round(6)).astype(int)


# ---------------------------------------------------------------- 근거 문장

def reason_text(signal: str, value: float, usual: float, pct: float) -> str:
    """근거 한 줄 (템플릿, LLM 사용 안 함)."""
    tail = f"평소보다 약 {abs(pct):.0f}% {'많이' if pct > 0 else '적게'} 예상"
    if signal == "rain_mm":
        head = f"비 예보({value:g}mm)로"
    elif signal == "temp_diff":
        head = f"기온이 최근 평균보다 {abs(value):.0f}도 {'높아' if value > 0 else '낮아'}"
    elif signal in EVENT_TEXT:
        head = EVENT_TEXT[signal]
    else:
        head = f"{signal} 신호({value:g})로"
    return f"{head} {tail}"


def usual_values(train: pd.DataFrame, signal_cols: list[str], kinds: dict[str, set]) -> dict[str, float]:
    """신호마다 '평소 값'.  비·학사일정·행사 = 0 (없는 날이 평소), 기온 등 연속값 = 최근 28일 중앙값."""
    recent = train[train["date"] > train["date"].max() - pd.Timedelta(days=RECENT_DAYS)].drop_duplicates("date")
    usual = {}
    for c in signal_cols:
        if c in ZERO_USUAL or kinds.get(c, set()) <= ZERO_FILL_KINDS:
            usual[c] = 0.0
        else:
            usual[c] = round(float(recent[c].median()), 1)
    return usual


def signal_sources(signals: pd.DataFrame, store_id: str, date, close_time: str) -> dict[str, str]:
    """그 날짜에 실제로 쓴 발표본(issue_time까지 공개된 것 중 가장 늦은 것)의 출처 주소."""
    s = signals[(signals["store_id"] == store_id) & (signals["date"] == date)
                & (signals["published_at"] <= issue_time(date, close_time))]
    return s.sort_values("published_at").groupby("signal")["source_url"].last().to_dict()


# ---------------------------------------------------------------- 내일 예측

def predict_next_day(sales: pd.DataFrame, signals: pd.DataFrame | None, groups: list[str], model_name: str,
                     calibration: dict[str, float] | None = None, close_time: str = DEFAULT_CLOSE_TIME,
                     prep_mode: str = "균형", target_date=None, menus: list[str] | None = None,
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

    # 1) 전체 기록으로 다시 학습 → 예측 (+ 채택된 범위 보정)
    model = make_model(model_name, groups=groups, **model_kwargs).fit(train)
    q = model.predict(rows)
    if calibration:
        q = apply_calibration(q.assign(base=base_level(rows)), calibration)

    # 2) 근거: 신호 하나씩 '평소 값'으로 바꿔 다시 예측한 p50과 비교
    usual = usual_values(train, model.signal_cols, kinds)
    sources = signal_sources(signals, store_id, target, close_time) if names else {}
    reasons = [[] for _ in range(len(rows))]
    # 원재료도 모델 변수인 파생 신호(예: vacation → vacation_diff)는 따로 근거를 내지 않고 원재료와 함께 바꾼다.
    # 원재료가 평소 값이었다면 파생값(오늘 − 최근 평균)도 그만큼 달라진다: diff + (평소 값 − 오늘 값)
    linked = {s: [d for d, (src, _) in DERIVED_SIGNALS.items() if src == s and d in model.signal_cols]
              for s in model.signal_cols}
    folded = {d for ds in linked.values() for d in ds}
    for sig in model.signal_cols:
        value = rows[sig]
        if sig in folded or value.isna().all() or (value == usual[sig]).all():   # 자료가 없거나 이미 평소 값
            continue
        cf_rows = rows.assign(**{sig: usual[sig]}, **{d: rows[d] + (usual[sig] - value) for d in linked[sig]})
        cf = model.predict(cf_rows)["p50"]
        pct = (q["p50"] - cf) / cf.where(cf > 0) * 100
        for i in range(len(rows)):
            if pd.notna(pct[i]) and pd.notna(value[i]) and abs(pct[i]) >= REASON_MIN_PCT:
                reasons[i].append(Reason(signal=sig, effect_pct=round(float(pct[i]), 1),
                                         text=reason_text(sig, float(value[i]), usual[sig], float(pct[i])),
                                         source_url=sources.get(sig)))

    # 3) 준비량 + 결과 정리
    prep = prep_qty(q, prep_mode)
    out_rows = [
        ForecastRow(date=target.date(), menu=rows.at[i, "menu"],
                    pred=round(float(q.at[i, "p50"]), 1), p10=round(float(q.at[i, "p10"]), 1),
                    p90=round(float(q.at[i, "p90"]), 1), prep_qty=int(prep[i]), model=model_name,
                    reasons=sorted(reasons[i], key=lambda r: -abs(r.effect_pct)))
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


def main(store_dir: str | None = None) -> Path:
    sys.stdout.reconfigure(encoding="utf-8")
    store_dir = Path(store_dir or ROOT / "data" / "sample" / "sinchon-a")
    info = json.loads((store_dir / "store.json").read_text(encoding="utf-8"))
    bt_path = ARTIFACTS / info["store_id"] / "backtest.json"
    if not bt_path.exists():
        raise SystemExit(f"{bt_path}가 없습니다. 먼저 python -m ml.evaluate {store_dir} 를 실행하세요.")
    backtest = BacktestResult.model_validate_json(bt_path.read_text(encoding="utf-8"))

    sales = load_sales(store_dir / "sales.csv")
    signals = load_signals(store_dir / "signals.csv") if (store_dir / "signals.csv").exists() else None
    fc = predict_from_backtest(sales, signals, backtest, close_time=info.get("close_time", DEFAULT_CLOSE_TIME),
                               prep_mode=info.get("prep_mode", "균형"))
    path = write_forecast(fc)

    print(f"[{fc.store_id}] {fc.rows[0].date} 예측 ({fc.rows[0].model}, 신호: {', '.join(fc.signals_used) or '없음'})")
    for r in fc.rows:
        why = " / ".join(x.text for x in r.reasons)
        print(f"  {r.menu:<10} {r.pred:5.1f}개 ({r.p10:.0f}~{r.p90:.0f})  준비 {r.prep_qty}  {why}")
    print("  저장:", path)
    return path


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
