"""학습·예측용 표 만들기: 판매 이력 변수 + 달력 변수 + 외부 신호.

결과 표의 한 행 = (매장, 날짜, 메뉴) 하나. 열 = 모델이 볼 단서들 + 정답(qty).

★ 시점 규칙 (미래 정보 누수 방지)
  D일 예측은 D-1일 영업이 끝난 직후에 낸다:  issue_time(D) = (D-1일) + close_time
  → D일 행의 모든 변수는 issue_time(D) 시점에 알 수 있었던 정보로만 만든다.
     - 판매 이력: D-1일까지 (모든 lag·이동평균은 shift(1) 다음에 계산)
     - 외부 신호: published_at <= issue_time(D) 인 것 중 가장 늦게 공개된 값

이 파일의 순서
  1. 변수 이름 목록     모델이 어떤 변수를 쓰는지 (새 신호는 SIGNAL_GROUPS에 이름만 추가)
  2. 시점              issue_time
  3. 판매 이력          base_level, 이력 변수, 매장 전체 흐름
  4. 외부 신호          attach_signals (시점 규칙으로 거르기), 파생 신호(DERIVED_SIGNALS)
  5. build_frame       위를 모두 합친 표
  6. 파일 읽기          load_sales, load_signals
"""
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from contracts.schemas import DEFAULT_CLOSE_TIME
from ml.calendar_kr import HOLIDAYS
from ml.ingest import temp_tag

# ---------------------------------------------------------------- 1. 변수 이름 목록
HISTORY_FEATURES = ["lag_1", "lag_7", "lag_14", "same_wd_mean_4", "same_wd_min_4", "same_wd_max_4",
                    "mean_7", "mean_28", "sold_out_7", "days_since_start",
                    # 평소 수준(base_level) 대비 비율. 모델 목표가 '평소 대비 비율'이라 이력도 같은 단위로 준다.
                    # 하루 285개 바게트와 2개 쿠키가 '지난주가 평소보다 20% 많았다'를 같은 숫자로 보게 된다.
                    "r_lag_1", "r_lag_7", "r_mean_7", "r_same_wd",
                    # 매장 전체 판매의 흐름 (최근 7일 ÷ 28일, 어제 ÷ 28일). 메뉴 하나보다 덜 흔들려 성수기 시작·끝을 빨리 잡는다
                    "store_7_28", "store_lag1_28"]
CALENDAR_FEATURES = ["dow", "is_weekend", "is_holiday"]
# menu_temp = 이름의 아이스/핫 표기 (ingest.temp_tag). 메뉴 하나하나가 아니라 '아이스 음료끼리' 기온 효과를
# 함께 배우게 한다 (메뉴별로는 기록이 적어 따뜻한 음료의 추운 날 효과를 못 배웠음, REVIEW E 11/15)
CATEGORICAL_FEATURES = ["store_id", "menu", "menu_temp"]
BASE_FEATURES = CATEGORICAL_FEATURES + CALENDAR_FEATURES + HISTORY_FEATURES   # M1이 쓰는 변수 전부

# 외부 신호 묶음. 채택 여부는 묶음 단위로 정한다 (evaluate.py). 새 신호는 알맞은 묶음에 이름만 추가한다.
SIGNAL_GROUPS = {
    "weather": ["temp_diff", "rain_mm"],       # temp_diff = 기온 − 최근 28일 평균 (파생 신호, 아래 DERIVED_SIGNALS)
    # *_diff = 학사일정 − 최근 28일 평균 (파생). 방학이 시작되면 '최근 평균'이 한동안 학기 수준이라 늦게 따라간다.
    # 그 늦음을 모델이 알 수 있게 '기간이 바뀐 지 얼마나 됐는지'를 준다 (11/15: 검증 WAPE 0.279→0.219, bias +5%→+1%)
    "events":  ["exam_period", "vacation", "festival", "nearby_event",
                "exam_period_diff", "vacation_diff", "festival_diff"],
    "trend":   ["trend_level", "trend_slope"],  # 아직 이 신호를 만드는 수집기가 없다 (메뉴 유행은 AI 주의 안내로만 전달)
    "special": ["special_day"],                # 기념일(발렌타인·빼빼로데이·크리스마스 등)을 하나로 묶은 표시
}
ALL_SIGNALS = {name for names in SIGNAL_GROUPS.values() for name in names}
# 화면 비교표에 보여 주는 기본 모델 정의 (실제로 쓸 조합은 evaluate.py가 매장마다 고른다)
FEATURE_SETS = {"M1": [], "M2": ["weather"], "M3": ["weather", "events", "trend", "special"]}

ZERO_FILL_KINDS = {"calendar", "event"}   # 목록에 없으면 '해당 없음' → 0.  observed/forecast는 '모름' → NaN


# ---------------------------------------------------------------- 2. 시점

def _close_offset(close_time: str) -> pd.Timedelta:
    """'21:00' → 21시간.  자정을 넘겨 영업하는 매장(예: '02:00')은 23:59로 본다
    (그 뒤 판매는 포스에서 다음 날로 집계되므로)."""
    h, m = map(int, close_time.split(":"))
    if h < 5:
        h, m = 23, 59
    return pd.Timedelta(hours=h, minutes=m)


def issue_time(date, close_time: str = DEFAULT_CLOSE_TIME) -> pd.Timestamp:
    """D일 예측을 내는 시각 = D-1일 영업 종료 시각."""
    return pd.Timestamp(date).normalize() - pd.Timedelta(days=1) + _close_offset(close_time)


# ---------------------------------------------------------------- 3. 판매 이력

def base_level(frame: pd.DataFrame) -> pd.Series:
    """메뉴의 '평소 수준' = mean_28 → mean_7 → lag_1 (처음으로 값이 있는 것), 1 미만이면 1.
    CatBoost의 비율 목표(models.py), 비율 이력 변수, 범위 보정(calibration.py)이 모두 같은 기준을 쓴다."""
    return frame["mean_28"].fillna(frame["mean_7"]).fillna(frame["lag_1"]).fillna(1.0).clip(lower=1.0)


def _history_one_menu(g: pd.DataFrame, end: pd.Timestamp) -> pd.DataFrame:
    """메뉴 하나의 판매 기록 → 날짜별 이력 변수.

    날짜를 달력 전체로 펼친다 (기록이 없는 날 = 휴무 → NaN). 그래야 shift(7)이 정확히 '7일 전'이 된다.
    """
    first = g["date"].min()
    days = pd.date_range(first, end, freq="D")
    s = g.set_index("date").reindex(days)

    qty = s["qty"].astype(float)
    sold_out = s["sold_out"].map({True: 1.0, False: 0.0})   # 휴무일은 NaN 그대로
    past = qty.shift(1)                                     # ★ D일 행에는 D-1일까지만 보이게

    f = pd.DataFrame(index=days)
    f["qty"] = qty                                          # 정답 (예측 행에서는 NaN)
    f["sold_out"] = s["sold_out"]
    f["lag_1"] = past
    f["lag_7"] = qty.shift(7)
    f["lag_14"] = qty.shift(14)
    same_wd = pd.concat([qty.shift(7 * k) for k in range(1, 5)], axis=1)   # 7·14·21·28일 전 (같은 요일)
    f["same_wd_mean_4"] = same_wd.mean(axis=1)
    f["same_wd_min_4"] = same_wd.min(axis=1)                # M0의 예측 범위 아래쪽
    f["same_wd_max_4"] = same_wd.max(axis=1)                # M0의 예측 범위 위쪽
    f["mean_7"] = past.rolling(7, min_periods=1).mean()
    f["mean_28"] = past.rolling(28, min_periods=7).mean()
    f["sold_out_7"] = sold_out.shift(1).rolling(7, min_periods=1).sum()
    f["days_since_start"] = (days - first).days
    b = base_level(f)
    f["r_lag_1"], f["r_lag_7"] = f["lag_1"] / b, f["lag_7"] / b
    f["r_mean_7"], f["r_same_wd"] = f["mean_7"] / b, f["same_wd_mean_4"] / b
    return f


def _history(sales: pd.DataFrame, end: pd.Timestamp) -> pd.DataFrame:
    parts = []
    for (store_id, menu), g in sales.groupby(["store_id", "menu"], sort=False):
        f = _history_one_menu(g, end)
        f.insert(0, "menu", menu)
        f.insert(0, "store_id", store_id)
        parts.append(f.rename_axis("date").reset_index())
    return pd.concat(parts, ignore_index=True)


def _store_trend(frame: pd.DataFrame) -> pd.DataFrame:
    """매장 전체 하루 판매 합계의 흐름: store_7_28 = 최근 7일 평균 ÷ 최근 28일 평균, store_lag1_28 = 어제 ÷ 최근 28일 평균.
    D일 값은 D-1일까지의 판매로만 만든다 (shift(1)). 휴무일은 빈 값으로 두고 평균에서 빠진다."""
    parts = []
    for store_id, g in frame[frame["qty"].notna()].groupby("store_id"):
        total = g.groupby("date")["qty"].sum()
        days = pd.date_range(total.index.min(), frame["date"].max(), freq="D")
        past = total.reindex(days).shift(1)
        m28 = past.rolling(28, min_periods=7).mean()
        parts.append(pd.DataFrame({"store_id": store_id, "date": days,
                                   "store_7_28": (past.rolling(7, min_periods=3).mean() / m28).to_numpy(),
                                   "store_lag1_28": (past / m28).to_numpy()}))
    return frame.merge(pd.concat(parts), on=["store_id", "date"], how="left")


# ---------------------------------------------------------------- 4. 외부 신호

def attach_signals(frame: pd.DataFrame, signals: pd.DataFrame, signal_names: list[str],
                   close_time: str = DEFAULT_CLOSE_TIME) -> pd.DataFrame:
    """세로형 신호 → (시점 규칙으로 거른 뒤) 가로형으로 바꿔 frame에 붙인다."""
    known = set(signals["signal"])
    missing = [n for n in signal_names if n not in known]
    if missing:
        warnings.warn(f"signals에 없는 신호는 건너뜀: {missing}", stacklevel=2)
    names = [n for n in signal_names if n in known]
    if not names:
        return frame

    s = signals[signals["signal"].isin(names)].copy()
    s["issue"] = s["date"] - pd.Timedelta(days=1) + _close_offset(close_time)   # 그 날짜 예측을 내는 시각
    s = s[s["published_at"] <= s["issue"]]                            # ★ 그때 몰랐던 정보는 버린다
    s = s.sort_values("published_at").groupby(["store_id", "date", "signal"]).last()   # 가장 늦은 발표본
    wide = s["value"].unstack("signal").reset_index()                 # 세로형 → 가로형

    out = frame.merge(wide, on=["store_id", "date"], how="left")
    kinds = signals.groupby("signal")["kind"].agg(set)
    for n in names:
        if n not in out:                                              # 시점 규칙으로 전부 걸러진 신호
            out[n] = np.nan
        if kinds[n] <= ZERO_FILL_KINDS:
            out[n] = out[n].fillna(0.0)
    return out


def _diff_from_recent(signal: str, days: int = 28):
    """파생 신호 만드는 함수: '오늘 값 − 최근 28일 평균'. 판매 목표가 '최근 평균 대비 비율'이므로 신호도 같은 기준으로 맞춘다.
    최근 평균에는 오늘 값을 넣지 않고(shift(1)), 각 날짜의 값은 이미 그날의 시점 규칙을 지킨 값이다."""
    def make(frame: pd.DataFrame) -> pd.Series:
        day = frame.drop_duplicates(["store_id", "date"]).set_index(["store_id", "date"])[signal]
        parts = []
        for store_id, s in day.groupby(level="store_id"):
            s = s.droplevel("store_id")
            s = s.reindex(pd.date_range(s.index.min(), s.index.max(), freq="D"))
            recent = s.shift(1).rolling(days, min_periods=7).mean()
            parts.append(pd.DataFrame({"store_id": store_id, "date": s.index, "v": (s - recent).to_numpy()}))
        diff = pd.concat(parts).set_index(["store_id", "date"])["v"]
        return pd.Series(diff.reindex(pd.MultiIndex.from_frame(frame[["store_id", "date"]])).to_numpy(),
                         index=frame.index)
    return make


# 파생 신호 = 받은 신호로 계산해 만드는 신호.  이름 → (원재료 신호, 계산 함수)
# 새 파생 신호는 여기에 한 줄 추가하고 SIGNAL_GROUPS에 이름을 넣는다.
DERIVED_SIGNALS = {
    "temp_diff": ("temp_mean", _diff_from_recent("temp_mean")),
    "exam_period_diff": ("exam_period", _diff_from_recent("exam_period")),
    "vacation_diff": ("vacation", _diff_from_recent("vacation")),
    "festival_diff": ("festival", _diff_from_recent("festival")),
}


def available_signals(groups, signals: pd.DataFrame) -> list[str]:
    """신호 묶음들 → 이 signals 자료로 만들 수 있는 신호 이름 (받은 신호 + 원재료가 있는 파생 신호)."""
    have = set(signals["signal"])
    return [n for g in groups for n in SIGNAL_GROUPS[g]
            if n in have or (n in DERIVED_SIGNALS and DERIVED_SIGNALS[n][0] in have)]


def signals_in(groups, frame: pd.DataFrame) -> list[str]:
    """신호 묶음들 → frame에 실제로 열이 있는 신호 이름 (자료가 없는 신호는 빠진다)."""
    return [n for g in groups for n in SIGNAL_GROUPS[g] if n in frame.columns]


def feature_columns(model_name: str, frame: pd.DataFrame, groups=None) -> list[str]:
    """모델이 쓸 변수 목록. groups를 주면 그 신호 묶음을, 아니면 모델 이름(M1~M3)의 기본 묶음을 쓴다."""
    groups = FEATURE_SETS[model_name] if groups is None else groups
    return BASE_FEATURES + signals_in(groups, frame)


# ---------------------------------------------------------------- 5. 전체

def build_frame(sales: pd.DataFrame, signals: pd.DataFrame | None = None, signal_names: list[str] = (),
                predict_dates=None, close_time: str = DEFAULT_CLOSE_TIME) -> pd.DataFrame:
    """학습·예측용 표.

    sales         SalesRow 형식 (date, store_id, menu, qty, sold_out)
    signals       SignalRow 형식 (없으면 신호 없이)
    signal_names  붙일 신호 이름들 (보통 available_signals의 결과)
    predict_dates 주면, 최근 14일 안에 팔린 메뉴마다 qty=NaN인 예측 행을 추가
    close_time    영업 종료 시각 "21:00"

    반환: 학습 행(qty 있음) + 예측 행(qty=NaN). 휴무일·판매 기간 밖 날짜는 들어가지 않는다.
    """
    sales = sales.copy()
    sales["date"] = pd.to_datetime(sales["date"])
    predict_dates = pd.to_datetime(list(predict_dates)) if predict_dates is not None else pd.DatetimeIndex([])
    end = max([sales["date"].max(), *predict_dates])

    # 판매 이력 (학습 행 + 예측 행만 남긴다)
    h = _history(sales, end)
    is_train = h["qty"].notna()
    is_pred = pd.Series(False, index=h.index)
    if len(predict_dates):
        last = sales.groupby(["store_id", "menu"])["date"].max()
        store_last = sales.groupby("store_id")["date"].max()
        recent = last[last >= last.index.get_level_values("store_id").map(store_last) - pd.Timedelta(days=13)]
        alive = h.set_index(["store_id", "menu"]).index.isin(recent.index)   # 최근 14일 안에 팔린 메뉴만
        is_pred = pd.Series(alive, index=h.index) & h["date"].isin(predict_dates)
    frame = _store_trend(h[is_train | is_pred].reset_index(drop=True))

    # 메뉴 속성, 달력
    frame["menu_temp"] = frame["menu"].map(temp_tag)                  # 'ICE' / 'HOT' / '-'
    frame["dow"] = frame["date"].dt.day_of_week                       # 0=월 ... 6=일
    frame["is_weekend"] = (frame["dow"] >= 5).astype(int)
    frame["is_holiday"] = frame["date"].isin(HOLIDAYS).astype(int)

    # 외부 신호: 파생 신호는 원재료 이름으로 바꿔 붙인 뒤 계산한다
    if signals is not None and len(signal_names):
        raw = [DERIVED_SIGNALS[n][0] if n in DERIVED_SIGNALS else n for n in signal_names]
        frame = attach_signals(frame, signals, list(dict.fromkeys(raw)), close_time)   # 순서 유지하며 중복 제거
        for name, (needs, make) in DERIVED_SIGNALS.items():
            if needs in frame.columns:
                frame[name] = make(frame)
    return frame.sort_values(["store_id", "date", "menu"]).reset_index(drop=True)


# ---------------------------------------------------------------- 6. 파일 읽기

def to_kst(t) -> pd.Timestamp:
    """시각 하나 → 한국 시간(시간대 표시 없음). '2026-10-20T10:00:00+09:00'·'...Z'처럼 시간대가 붙어 오면 KST로 바꾼 뒤 뗀다."""
    t = pd.Timestamp(t)
    return t.tz_convert("Asia/Seoul").tz_localize(None) if t.tzinfo is not None else t


def load_sales(path) -> pd.DataFrame:
    return pd.read_csv(path, parse_dates=["date"])


def load_signals(path) -> pd.DataFrame:
    """SignalRow 형식 신호 파일 (.csv 또는 .json = SignalRow 객체들의 목록). 공개 시각은 한국 시간으로 맞춘다."""
    path = Path(path)
    if path.suffix.lower() == ".json":
        df = pd.DataFrame(json.loads(path.read_text(encoding="utf-8-sig")))
    else:
        df = pd.read_csv(path)
    return df.assign(date=pd.to_datetime(df["date"]).dt.normalize(),
                     published_at=pd.to_datetime(df["published_at"].map(to_kst)))
