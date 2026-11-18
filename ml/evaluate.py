"""모델 검증 → backtest.json.  "이 매장에서 어떤 모델·어떤 주변 정보가 실제로 잘 맞았나"를 과거 기록으로 확인한다.

시간순 교차검증 (rolling origin: 학습 기간을 늘려 가며)
    |------ 학습 ------|-검증1-|-검증2-|-검증3-|-검증4-|== 최종 테스트 ==|
    검증 k: 그 구간 시작 전 데이터 전부로 새 모델을 학습 → 구간 안의 각 날짜를 '하루 앞' 예측
            (구간 안에서는 재학습하지 않는다. 변수는 features.py가 이미 날마다 최신 판매로 계산해 둠)
    최종 테스트: 모델·신호·보정을 모두 정한 뒤 딱 한 번. 그 결과를 보고 아무것도 바꾸지 않는다.

run_backtest의 순서 (아래 함수들이 한 단계씩)
    1. plan_folds          검증 구간·최종 테스트 구간 나누기 (데이터 길이에 맞춰)
    2. choose_signals      신호 묶음의 모든 조합을 교차검증 → 조합 고르기(pick_combo) + 묶음별 이유(decide)
    3. comparison_table    화면용 M0·M1·M2·M3 비교표
    4. check_calibration   범위 보정을 쓸지 (ml/calibration.py)
    5. final_test          최종 테스트 한 번
    6. data_note           화면·발표에서 그대로 밝힐 설명

지표는 ml/metrics.py, 범위 보정은 ml/calibration.py에 있다.
"""
import datetime as dt
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

import pandas as pd

from contracts.schemas import BacktestResult
from ml import progress
from ml.calibration import apply_calibration, below_rates, check_calibration, fit_calibration
from ml.features import (DEFAULT_CLOSE_TIME, FEATURE_SETS, SIGNAL_GROUPS, available_signals, base_level, build_frame,
                         signals_in)
from ml.metrics import bootstrap_wape_change, coverage, score, scored
from ml.models import SHORT_DATA_DAYS, make_model
from ml.paths import ARTIFACTS


# ---------------------------------------------------------------- 1. 검증 구간 나누기

@dataclass
class FoldPlan:
    folds: list[tuple[pd.Timestamp, pd.Timestamp]]   # 검증 구간들 (시작, 끝) — 끝 날짜 포함
    test: tuple[pd.Timestamp, pd.Timestamp] | None    # 최종 테스트 구간 (없을 수 있음)
    short: bool                                       # 짧은 데이터 모드인가
    note: str                                         # data_note에 들어갈 설명


# (최종 테스트 일수, 검증 구간 일수, 검증 구간 개수, 최소 학습 일수) — 앞에서부터 들어맞는 첫 설정을 쓴다
PLANS_NORMAL = [(28, 28, 4, 56)]
PLANS_SHORT = [(7, 7, 2, 14), (0, 7, 2, 14), (0, 7, 1, 14)]


def plan_folds(dates) -> FoldPlan:
    """판매 날짜들 → 검증 구간·최종 테스트 구간.  데이터 길이에 맞춰 자동으로 줄인다."""
    dates = pd.DatetimeIndex(pd.to_datetime(pd.Series(dates).unique())).sort_values()
    first, last = dates[0], dates[-1]
    span = (last - first).days + 1                    # 달력 일수 (휴무일 포함)
    n_days = len(dates)
    short = n_days < SHORT_DATA_DAYS

    for test_days, fold_days, n_folds, min_train in (PLANS_SHORT if short else PLANS_NORMAL):
        if span < min_train + fold_days * n_folds + test_days:
            continue
        day = pd.Timedelta(days=1)
        test = (last - (test_days - 1) * day, last) if test_days else None
        end = (test[0] - day) if test else last       # 마지막 검증 구간의 끝
        folds = []
        for _ in range(n_folds):
            start = end - (fold_days - 1) * day
            folds.insert(0, (start, end))             # 앞쪽(과거)부터 순서대로 놓이게
            end = start - day

        parts = [f"판매 기록 {n_days}일"]
        if short:
            parts.append(f"검증 {n_folds}개 구간×{fold_days}일로 짧아 결과의 변동이 큼")
        if test is None:
            parts.append("최종 테스트 기간을 따로 둘 만큼 길지 않아 검증 구간 결과만 보고함")
        return FoldPlan(folds, test, short, ". ".join(parts))

    raise ValueError(f"판매 기록이 {n_days}일(달력 {span}일)뿐이라 검증할 수 없습니다. 최소 21일이 필요합니다.")


# ---------------------------------------------------------------- 교차검증

KEEP_COLS = ["store_id", "date", "menu", "qty", "sold_out"]


def cross_val_predict(frame: pd.DataFrame, model_name: str, folds, **model_kwargs) -> pd.DataFrame:
    """검증 구간마다 '그 전 데이터로만' 학습해서 구간 안을 예측한다.
    최종 테스트도 같은 함수에 구간 하나([test])를 넣어 계산한다.

    반환(예측표): 검증 행마다 실제값 + 예측(p10…p90, pred) + fold 번호 + train_last(학습에 쓴 마지막 날짜)
                 + base(평소 수준, 범위 보정에 씀).  train_last < 구간 시작일 이어야 한다 (테스트로 확인).
    """
    labeled = frame[frame["qty"].notna()]
    out = []
    for k, (start, end) in enumerate(folds):
        train = labeled[labeled["date"] < start]
        valid = labeled[(labeled["date"] >= start) & (labeled["date"] <= end)]
        model = make_model(model_name, **model_kwargs).fit(train)
        pred = model.predict(valid)
        out.append(valid[KEEP_COLS].join(pred).assign(fold=k, train_last=train["date"].max(),
                                                      base=base_level(valid)))
    return pd.concat(out, ignore_index=True)


class CrossValidator:
    """신호 묶음 조합 → 교차검증 (예측표, 점수).  실제로 쓰는 신호가 같은 조합은 한 번만 돌린다
    (예: 유행 신호 자료가 없으면 [날씨]와 [날씨, 유행]은 같은 모델)."""

    def __init__(self, frame: pd.DataFrame, folds, model_kwargs: dict):
        self.frame, self.folds, self.model_kwargs = frame, folds, model_kwargs
        self._done: dict[tuple, tuple[pd.DataFrame, dict]] = {}

    def key(self, groups) -> tuple:
        return tuple(signals_in(groups, self.frame))

    def run(self, groups) -> tuple[pd.DataFrame, dict]:
        key = self.key(groups)
        if key not in self._done:
            label = model_label(groups)
            preds = cross_val_predict(self.frame, label, self.folds, groups=list(groups), **self.model_kwargs)
            self._done[key] = (preds, score(preds, label))
            progress.emit("trial", groups=list(groups), wape=round(self._done[key][1]["wape"], 4))   # 화면: 방금 시험한 조합과 오차
        return self._done[key]


# ---------------------------------------------------------------- 2. 신호 채택

GROUP_LABELS = {"weather": "날씨", "events": "학사일정·행사", "trend": "유행", "special": "기념일"}
MIN_GAIN_PCT = 3.0   # 전체 오차가 이만큼(%) 이상 줄어야 '나아졌다'고 본다.
# 11/17 리허설: 관계없는 신호(검증 기간 내내 0인 기념일)를 넣기만 해도 나무 모양이 바뀌어 오차가 2%쯤 흔들렸다.


def model_label(groups) -> str:
    """채택된 신호 묶음 → 모델 이름.  없음=M1, 날씨만=M2, 학사일정·행사·유행 중 하나라도=M3.
    (날씨는 빠지고 행사만 채택돼도 M3라고 부른다. 실제로 쓴 신호는 signals_used·decisions에 있다.)"""
    groups = set(groups)
    if not groups:
        return "M1"
    return "M2" if groups <= {"weather"} else "M3"


def beats(after: dict, before: dict) -> tuple[bool, int, float]:
    """after가 before보다 나은가 → (통과 여부, 개선된 구간 수, 전체 WAPE 변화 %).
    통과 조건: 전체 WAPE가 MIN_GAIN_PCT% 이상 줄고, 검증 구간의 과반에서 WAPE가 줄었을 때."""
    improved = sum(a < b for a, b in zip(after["wape_by_fold"], before["wape_by_fold"]))
    change = (after["wape"] - before["wape"]) / before["wape"] * 100
    return change <= -MIN_GAIN_PCT and improved > len(before["wape_by_fold"]) / 2, improved, change


def pick_combo(scores: dict[tuple, dict]) -> list[str]:
    """{조합(묶음 이름 튜플): 교차검증 점수} → 고른 조합.  () = 신호 없음(M1).
    1) 신호 없음보다 beats()를 통과한 조합 중 전체 WAPE가 가장 낮은 것
    2) 그 조합 안의 묶음마다 '빼면 나빠지는가'(beats)를 확인해, 제 몫을 못 하는 묶음을 하나씩 뺀다
       (빼도 가장 덜 나빠지는 것부터). 남은 조합이 신호 없음보다 낫지 않으면 [] (신호 없이 M1).
    1등만 고르면 우연히 좋게 나온 조합을 고를 위험이 커서 이 조건들을 둔다."""
    passing = [c for c in scores if c and beats(scores[c], scores[()])[0]]
    if not passing:
        return []
    combo = min(passing, key=lambda c: scores[c]["wape"])
    without = lambda c, g: tuple(x for x in c if x != g)
    while combo:
        weak = [g for g in combo if not beats(scores[combo], scores[without(combo, g)])[0]]
        if not weak:
            break
        combo = without(combo, min(weak, key=lambda g: scores[without(combo, g)]["wape"]))
        if combo and not beats(scores[combo], scores[()])[0]:
            return []
    return list(combo)


def decide(group: str, signals: list[str], before: dict | None, after: dict | None,
           adopted: bool | None = None, note: str | None = None) -> dict:
    """신호 묶음 하나를 넣기 전(before)·후(after)의 교차검증 점수 → 화면에 보여 줄 결정 한 줄 (SignalDecision 형식의 dict).

    adopted를 주지 않으면 beats()의 조건으로 정한다. choose_signals는 채택 여부를 정해서 넘기고,
    이 함수는 그 묶음을 넣었을 때와 뺐을 때의 차이로 이유 문장만 만든다.
    """
    label = GROUP_LABELS.get(group, group)
    if after is None:                                  # 자료가 없거나(note 없음) 평가할 수 없음(note)
        return dict(signal_group=group, signals=list(signals), adopted=False, wape_change_pct=0.0,
                    folds_improved=0, folds_total=0, reason=f"{label} 신호 {note or '자료가 아직 없어 평가하지 못함'}")

    total = len(before["wape_by_fold"])
    passed, improved, change = beats(after, before)
    adopted = passed if adopted is None else adopted

    if adopted:
        reason = f"{label} 신호를 넣으니 검증 {total}개 구간 중 {improved}개에서 오차가 줄어 사용함 (전체 오차 {-change:.1f}% 감소)"
    elif change >= 0:
        reason = f"{label} 신호는 이 매장 판매 예측을 개선하지 못해 쓰지 않음 ({total}개 구간 중 {improved}개만 개선)"
    elif improved <= total / 2:
        reason = (f"{label} 신호는 전체 오차를 {-change:.1f}% 줄였지만 {total}개 구간 중 {improved}개에서만 "
                  f"개선돼 우연일 수 있어 쓰지 않음")
    else:
        reason = (f"{label} 신호는 전체 오차를 {-change:.1f}% 줄였지만 기준({MIN_GAIN_PCT:.0f}%)보다 작아 "
                  f"우연한 흔들림과 구분되지 않아 쓰지 않음")
    return dict(signal_group=group, signals=list(signals), adopted=adopted, wape_change_pct=round(change, 2),
                folds_improved=improved, folds_total=total, reason=reason)


def choose_signals(frame: pd.DataFrame, plan: FoldPlan, cv: CrossValidator) -> tuple[list[str], list[dict], int]:
    """자료가 있는 신호 묶음의 모든 조합(묶음 n개면 2^n가지)을 같은 검증 구간에서 비교한다.
    돌려주는 값: (채택한 묶음들, 묶음별 결정, 비교한 조합 수)"""
    in_folds = pd.Series(False, index=frame.index)
    for start, end in plan.folds:
        in_folds |= (frame["date"] >= start) & (frame["date"] <= end)
    has_data = [g for g in SIGNAL_GROUPS if signals_in([g], frame)]
    # 검증 구간 안에서 값이 한 번도 바뀌지 않는 묶음은 효과를 잴 수 없다 → 평가하지 않는다 (예: 기념일이 없던 기간)
    flat = {g for g in has_data
            if all(frame.loc[in_folds, c].nunique(dropna=True) <= 1 for c in signals_in([g], frame))}
    present = [g for g in has_data if g not in flat]

    combos = [c for r in range(len(present) + 1) for c in combinations(present, r)]
    scores = {c: cv.run(c)[1] for c in combos}
    adopted = pick_combo(scores)

    decisions = []                                     # 묶음마다 이유: 고른 조합에서 그 묶음을 넣었을 때 vs 뺐을 때
    for group in SIGNAL_GROUPS:
        if group in flat:
            decisions.append(decide(group, signals_in([group], frame), None, None,
                                    note="자료는 있지만 검증 기간에 값이 한 번도 바뀌지 않아 효과를 평가할 수 없음"))
        elif group not in present:
            decisions.append(decide(group, [], None, None))
        else:
            without = tuple(g for g in adopted if g != group)
            with_ = tuple(g for g in present if g in adopted or g == group)
            decisions.append(decide(group, signals_in([group], frame), scores[without], scores[with_],
                                    adopted=group in adopted))
    return adopted, decisions, len(combos)


# ---------------------------------------------------------------- 3. 화면용 비교표

def comparison_table(cv: CrossValidator, cv_m0: pd.DataFrame, adopted: list[str]) -> list[dict]:
    """M0 + 기본 정의의 M1·M2·M3 점수 (+ 채택 조합이 그중에 없으면 따로 한 줄)."""
    table, seen = [score(cv_m0, "M0")], set()
    for name in ["M1", "M2", "M3"]:
        key = cv.key(FEATURE_SETS[name])
        if key not in seen:                            # 신호 자료가 없어 앞 모델과 같으면 생략
            seen.add(key)
            table.append(score(cv.run(FEATURE_SETS[name])[0], name))
    if cv.key(adopted) not in seen:
        table.append(score(cv.run(adopted)[0], f"{model_label(adopted)}(채택 신호만)"))
    return table


# ---------------------------------------------------------------- 5. 최종 테스트

def final_test(frame: pd.DataFrame, plan: FoldPlan, adopted: list[str], shifts: dict | None,
               model_kwargs: dict) -> tuple[list[dict], dict, int]:
    """위에서 모두 정한 뒤 딱 한 번: M0 vs 채택 모델(보정 적용).
    돌려주는 값: (점수 두 줄, 보정 전후 비교, 품절로 채점에서 뺀 행 수).  테스트 구간이 없으면 ([], {}, 0)."""
    if plan.test is None:
        return [], {}, 0
    chosen = model_label(adopted)
    t_m0 = cross_val_predict(frame, "M0", [plan.test])
    t_raw = cross_val_predict(frame, chosen, [plan.test], groups=adopted, **model_kwargs)
    t_final = apply_calibration(t_raw, shifts) if shifts is not None else t_raw
    effect = {}
    if shifts is not None:
        d_raw, d_cal = scored(t_raw), scored(t_final)
        effect = dict(test_coverage_before=round(coverage(d_raw["qty"], d_raw["p10"], d_raw["p90"]), 3),
                      test_coverage_after=round(coverage(d_cal["qty"], d_cal["p10"], d_cal["p90"]), 3),
                      test_below_before=below_rates(t_raw), test_below_after=below_rates(t_final))
    return [score(t_m0, "M0"), score(t_final, chosen)], effect, int(t_m0["sold_out"].astype(bool).sum())


# ---------------------------------------------------------------- 6. 설명 문장

def data_note(plan: FoldPlan, n_combos: int, adopted: list[str], cv_m0: pd.DataFrame, chosen_cv: pd.DataFrame,
              n_sold_out: int, calibration_reason: str) -> str:
    """화면과 발표에서 그대로 밝힐 설명: 기록 길이, 고른 신호, 기준선 대비 개선과 그 확실함, 품절 제외, 범위 보정."""
    chosen = model_label(adopted)
    notes = [plan.note]
    if n_combos > 1:
        picked = ", ".join(GROUP_LABELS.get(g, g) for g in adopted) or "신호 없음"
        notes.append(f"신호 조합 {n_combos}가지를 모두 비교해 '{picked}' 선택")
    b = bootstrap_wape_change(cv_m0, chosen_cv)
    if cv_m0["date"].nunique() < 4 * 7:                   # 7일 묶음이 4개도 안 되면 구간을 믿기 어렵다
        notes.append(f"검증 구간에서 {chosen}의 오차가 M0 대비 {b['change_pct']:+.1f}% (기간이 짧아 우연 여부는 판단하지 않음)")
    else:
        sure = "우연이라 보기 어려움" if b["hi"] < 0 else "우연일 수 있음"
        notes.append(f"검증 구간에서 {chosen}의 오차가 M0 대비 {b['change_pct']:+.1f}% "
                     f"(95% 구간 {b['lo']:+.1f}~{b['hi']:+.1f}%, {sure})")
    if n_sold_out:
        notes.append(f"품절로 실제 수요를 알 수 없는 {n_sold_out}개 행은 채점에서 뺌")
    notes.append(calibration_reason)
    return ". ".join(notes)


# ---------------------------------------------------------------- 전체

def run_backtest(sales: pd.DataFrame, signals: pd.DataFrame | None = None,
                 close_time: str = DEFAULT_CLOSE_TIME, **model_kwargs) -> BacktestResult:
    """매장 하나의 판매(+신호) → BacktestResult.  model_kwargs는 테스트용 (예: iterations=30)."""
    store_ids = sales["store_id"].unique()
    if len(store_ids) != 1:
        raise ValueError(f"매장 하나씩 평가합니다. 받은 매장: {list(store_ids)}")
    store_id = str(store_ids[0])

    names = []
    if signals is not None:
        signals = signals[signals["store_id"] == store_id]
        names = available_signals(SIGNAL_GROUPS, signals)
    frame = build_frame(sales, signals, names, close_time=close_time)

    plan = plan_folds(frame.loc[frame["qty"].notna(), "date"])                      # 1
    cv = CrossValidator(frame, plan.folds, model_kwargs)
    adopted, decisions, n_combos = choose_signals(frame, plan, cv)                  # 2
    chosen_cv = cv.run(adopted)[0]
    cv_m0 = cross_val_predict(frame, "M0", plan.folds)
    cv_scores = comparison_table(cv, cv_m0, adopted)                                # 3

    check = check_calibration(chosen_cv)                                            # 4
    shifts = fit_calibration(chosen_cv) if check["adopted"] else None   # 채택되면 검증 구간 전체의 오차로 이동량을 정한다
    calibration = dict(method="conformal-ratio", **check, n_rows=len(scored(chosen_cv)),
                       shifts={k: round(v, 4) for k, v in shifts.items()} if shifts else {})

    test_scores, effect, n_sold_out_test = final_test(frame, plan, adopted, shifts, model_kwargs)   # 5
    calibration.update(effect)
    n_sold_out = int(cv_m0["sold_out"].astype(bool).sum()) + n_sold_out_test

    day = lambda t: pd.Timestamp(t).date()
    return BacktestResult(
        store_id=store_id, generated_at=dt.datetime.now().replace(microsecond=0),
        folds=[(day(s), day(e)) for s, e in plan.folds],
        test_period=(day(plan.test[0]), day(plan.test[1])) if plan.test else None,
        cv_scores=cv_scores, decisions=decisions, chosen_model=model_label(adopted), test_scores=test_scores,
        data_note=data_note(plan, n_combos, adopted, cv_m0, chosen_cv, n_sold_out, check["reason"]),      # 6
        calibration=calibration,
    )


def write_backtest(result: BacktestResult, out_root: Path = ARTIFACTS) -> Path:
    path = Path(out_root) / result.store_id / "backtest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return path
