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
from ml.features import (DEFAULT_CLOSE_TIME, FEATURE_SETS, SIGNAL_FAMILIES, SIGNAL_GROUPS, available_signals, base_level,
                         build_frame, expand, signals_in)
from ml.metrics import bootstrap_wape_change, coverage, days_won, score, scored
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
# 11/20: 기록이 길면(달력으로 약 10개월 이상) 검증 구간을 8개(약 7개월 반)로 쓴다.
#   4개(최근 넉 달)뿐이면 학기에 한 번 오는 일(시험기간, 방학의 시작과 끝, 축제)이 그 안에 한두 번밖에 없어
#   그 정보가 실제로 도움이 되는지 잴 수가 없었다 (가상 매장: 방학 효과를 심어 뒀는데도 채택되지 않았다).
#   ★ 평가 시간이 그만큼 늘어난다 (구간 수에 비례).
PLANS_NORMAL = [(28, 28, 8, 56), (28, 28, 4, 56)]
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
        keep = KEEP_COLS + [c for c in ("price",) if c in valid]             # 판매가(있으면): 금액 환산에 쓴다
        out.append(valid[keep].join(pred).assign(fold=k, train_last=train["date"].max(),
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
            s = self._done[key][1]                                              # 화면: 방금 시험한 조합과 하루에 틀린 개수
            progress.emit("trial", groups=list(groups), wape=round(s["wape"], 4), miss=round(miss_per_day(s), 1))
        return self._done[key]


# ---------------------------------------------------------------- 2. 신호 채택

GROUP_LABELS = {"temp": "기온", "rain": "비", "exam": "시험기간", "vacation": "방학", "festival": "학교 축제", "nearby": "근처 행사",
                "trend": "유행", "special": "기념일",
                "weather": "날씨", "events": "학사일정·행사"}       # 분야 이름 (예전 결과 파일, 설명 문장)
MIN_GAIN_PCT = 3.0   # 전체 오차가 이만큼(%) 이상 줄어야 '나아졌다'고 본다.
MIN_FOLDS_SEEN = 2   # 그 정보의 값이 바뀌는 검증 구간이 적어도 이만큼 있어야 판단한다 (한 기간만 보고 정하지 않는다)
# 11/17 리허설: 관계없는 신호(검증 기간 내내 0인 기념일)를 넣기만 해도 나무 모양이 바뀌어 오차가 2%쯤 흔들렸다.


def miss_per_day(s) -> float:
    """점수 한 줄 → 하루에 남거나 모자란 개수 (모든 메뉴 합)."""
    s = s if isinstance(s, dict) else s.model_dump()
    return (s["over"] + s["under"]) / max(s["days"], 1)


def model_label(groups) -> str:
    """채택된 신호 묶음 → 모델 이름.  없음=M1, 날씨만=M2, 학사일정·행사·유행 중 하나라도=M3.
    (날씨는 빠지고 행사만 채택돼도 M3라고 부른다. 실제로 쓴 신호는 signals_used·decisions에 있다.)"""
    groups = set(expand(groups))
    if not groups:
        return "M1"
    return "M2" if groups <= set(SIGNAL_FAMILIES["weather"]) else "M3"


def _folds_used(before: dict, mask) -> list[int]:
    """개선 여부를 셀 구간의 번호들. mask(구간마다 True/False)가 없으면 모든 구간."""
    n = len(before["wape_by_fold"])
    return [i for i in range(n) if mask is None or mask[i]]


def beats(after: dict, before: dict, mask=None) -> tuple[bool, int, float]:
    """after가 before보다 나은가 → (통과 여부, 개선된 구간 수, 전체 WAPE 변화 %).
    통과 조건: 전체 WAPE가 MIN_GAIN_PCT% 이상 줄고, 구간의 과반에서 WAPE가 줄었을 때.

    mask = 구간마다 '넣어 본 정보의 값이 그 구간 안에서 바뀌는가'. 주면 바뀌는 구간에서만 개선 여부를 센다.
    값이 한 번도 바뀌지 않는 구간(예: 기념일이 없던 달, 내내 학기 중이던 달)에서는 그 정보가 도움이 되는지 알 수 없고,
    오차가 줄었는지 늘었는지는 우연일 뿐이다 → 그런 구간까지 세면 가끔 오는 일의 정보는 과반을 채울 수 없다.
    전체 WAPE 변화는 모든 구간으로 잰다 (가끔 오는 일이라도 전체 오차를 MIN_GAIN_PCT% 이상 줄여야 한다).
    값이 바뀌는 구간이 한 곳뿐이면 통과시키지 않는다: 한 기간에서만 좋았던 정보는 쓰지 않는다 (검증 구간 자체가 하나뿐인 짧은 기록은 예외)."""
    used = _folds_used(before, mask)
    improved = sum(after["wape_by_fold"][i] < before["wape_by_fold"][i] for i in used)
    change = (after["wape"] - before["wape"]) / before["wape"] * 100
    enough = len(used) >= min(MIN_FOLDS_SEEN, len(before["wape_by_fold"]))
    return enough and change <= -MIN_GAIN_PCT and improved > len(used) / 2, improved, change


def pick_combo(scores: dict[tuple, dict], masks: dict[str, list[bool]] | None = None) -> list[str]:
    """{조합(묶음 이름 튜플): 교차검증 점수} → 고른 조합.  () = 신호 없음(M1).
    아래 두 조건을 모두 채우는 조합 가운데 전체 WAPE가 가장 낮은 것을 고른다. 없으면 [] (신호 없이 M1).
      1) 신호 없음보다 낫다 (beats)
      2) 무임승차하는 묶음이 없다: 묶음을 하나씩 빼 보면 매번 나빠진다 (beats)
    WAPE 1등만 고르면 우연히 좋게 나온 조합이나, 한 묶음 덕에 좋아진 조합에 다른 묶음이 얹혀 가는 것을 고를 위험이 커서 2)를 둔다.

    11/19 고침: 전에는 WAPE 1등 조합에서 약한 묶음을 하나씩 빼 나가다가, 도중의 조합이 1)을 못 채우면 '채택 없음'으로 끝냈다.
    그래서 혼자서도 기준을 통과하는 묶음이 있는데 채택되지 않는 일이 있었다 (첫 실매장: 날씨 −4.9%, 2구간 모두 개선인데 미채택).
    기준(MIN_GAIN_PCT, 과반 구간)은 그대로다."""
    without = lambda c, g: tuple(x for x in c if x != g)      # noqa: E731
    # masks = {묶음: 구간마다 그 묶음의 값이 바뀌는가}. 조합 전체를 볼 때는 그중 하나라도 바뀌는 구간을 센다 (beats의 mask)
    one = lambda g: masks[g] if masks else None                # noqa: E731
    any_of = lambda c: [any(m) for m in zip(*(masks[g] for g in c))] if masks else None   # noqa: E731
    solid = [c for c in scores if c and beats(scores[c], scores[()], any_of(c))[0]
             and all(beats(scores[c], scores[without(c, g)], one(g))[0] for g in c)]
    return list(min(solid, key=lambda c: scores[c]["wape"])) if solid else []


def decide(group: str, signals: list[str], before: dict | None, after: dict | None,
           adopted: bool | None = None, note: str | None = None, together: str | None = None, mask=None) -> dict:
    """신호 묶음 하나를 넣기 전(before)·후(after)의 교차검증 점수 → 화면에 보여 줄 결정 한 줄 (SignalDecision 형식의 dict).

    adopted를 주지 않으면 beats()의 조건으로 정한다. choose_signals는 채택 여부를 정해서 넘기고,
    이 함수는 그 묶음을 넣었을 때와 뺐을 때의 차이로 이유 문장만 만든다.
    mask = 구간마다 이 정보의 값이 바뀌는가 (beats와 같다). 주면 바뀌는 구간만 세고, 문장에도 그렇게 적는다.
    together = 분야 이름. 묶음 하나로는 기준을 못 넘지만 같은 분야의 묶음을 모두 넣으면 넘어서 함께 쓰는 경우다
               (before·after는 그 분야 전체를 뺐을 때·넣었을 때의 점수).
    """
    label = GROUP_LABELS.get(group, group)
    if after is None:                                  # 자료가 없거나(note 없음) 평가할 수 없음(note)
        return dict(signal_group=group, signals=list(signals), adopted=False, wape_change_pct=0.0,
                    folds_improved=0, folds_total=0, reason=f"{label} 신호 {note or '자료가 아직 없어 평가하지 못함'}")

    total = len(_folds_used(before, mask))
    passed, improved, change = beats(after, before, mask)
    adopted = passed if adopted is None else adopted
    # 일부 구간만 셌으면 그렇게 적는다 ("값이 바뀐 5개 구간 중 4개")
    spans = f"값이 바뀐 {total}개 구간" if total < len(before["wape_by_fold"]) else f"검증 {total}개 구간"

    if adopted and together:
        reason = (f"{label} 신호는 혼자서는 기준에 못 미치지만, {GROUP_LABELS.get(together, together)} 정보를 함께 넣으면 "
                  f"{spans} 중 {improved}개에서 오차가 줄어 함께 사용함 (전체 오차 {-change:.1f}% 감소)")
    elif adopted:
        reason = f"{label} 신호를 넣으니 {spans} 중 {improved}개에서 오차가 줄어 사용함 (전체 오차 {-change:.1f}% 감소)"
    elif total < min(MIN_FOLDS_SEEN, len(before["wape_by_fold"])):
        reason = f"{label} 신호는 값이 바뀐 검증 구간이 {total}개뿐이라 한 기간만 보고 정할 수 없어 쓰지 않음"
    elif change >= 0:
        reason = f"{label} 신호는 이 매장 판매 예측을 개선하지 못해 쓰지 않음 ({spans} 중 {improved}개만 개선)"
    elif improved <= total / 2:
        reason = (f"{label} 신호는 전체 오차를 {-change:.1f}% 줄였지만 {spans} 중 {improved}개에서만 "
                  f"개선돼 우연일 수 있어 쓰지 않음")
    else:
        reason = (f"{label} 신호는 전체 오차를 {-change:.1f}% 줄였지만 기준({MIN_GAIN_PCT:.0f}%)보다 작아 "
                  f"우연한 흔들림과 구분되지 않아 쓰지 않음")
    return dict(signal_group=group, signals=list(signals), adopted=adopted, wape_change_pct=round(change, 2),
                folds_improved=improved, folds_total=total, reason=reason)


def choose_signals(frame: pd.DataFrame, plan: FoldPlan, cv: CrossValidator) -> tuple[list[str], list[dict], int]:
    """어떤 신호 묶음을 쓸지 같은 검증 구간에서 두 단계로 고른다. 기준은 어디서나 같다 (beats: 전체 오차 3% 이상 감소 + 과반 구간 개선).
    개선된 구간은 그 정보의 값이 바뀌는 구간에서만 센다 (가끔 오는 일의 정보도 공정하게 재려는 것: beats의 mask).

      1) 분야 단위 (날씨 · 학사일정·행사 · 유행 · 기념일): 자료가 있는 분야의 모든 조합을 비교해 고른다 (pick_combo)
      2) 분야 안의 묶음 단위 (날씨 = 기온·비, 학사일정·행사 = 시험기간·방학·학교 축제·근처 행사):
         다른 분야는 정해진 대로 두고, 그 분야의 묶음을 하나씩 넣어 본다. 넣을 때마다 기준을 넘는 것만 (가장 좋은 것부터) 더한다.
         → 방학은 듣지만 시험기간은 안 듣는 가게면 방학만 쓴다. 1)에서 떨어진 분야라도 혼자 기준을 넘는 묶음은 쓴다.
         하나도 혼자서는 못 넘는데 1)에서 분야 전체로는 넘었다면, 전체를 그대로 쓴다 (함께일 때만 나오는 효과).

    묶음마다 조합을 다 해 보지 않는 이유: 묶음이 8개면 256가지라 오래 걸리고, 많이 해 볼수록 우연히 좋은 조합을 고를 위험이 커진다.
    돌려주는 값: (채택한 묶음들, 묶음별 결정, 비교한 조합 수)"""
    in_folds = pd.Series(False, index=frame.index)
    for start, end in plan.folds:
        in_folds |= (frame["date"] >= start) & (frame["date"] <= end)
    has_data = [g for g in SIGNAL_GROUPS if signals_in([g], frame)]
    # 검증 구간 안에서 값이 한 번도 바뀌지 않는 묶음은 효과를 잴 수 없다 → 평가하지 않는다 (예: 기념일이 없던 기간)
    flat = {g for g in has_data
            if all(frame.loc[in_folds, c].nunique(dropna=True) <= 1 for c in signals_in([g], frame))}
    present = {fam: [g for g in parts if g in has_data and g not in flat] for fam, parts in SIGNAL_FAMILIES.items()}
    families = [fam for fam in SIGNAL_FAMILIES if present[fam]]
    # 구간마다 그 묶음의 값이 바뀌는가 → 개선된 구간은 값이 바뀌는 구간에서만 센다 (beats의 mask)
    in_fold = [(frame["date"] >= start) & (frame["date"] <= end) for start, end in plan.folds]
    varies = {g: [any(frame.loc[rows, c].nunique(dropna=True) > 1 for c in signals_in([g], frame)) for rows in in_fold]
              for g in has_data}
    fam_varies = {fam: [any(v) for v in zip(*(varies[g] for g in present[fam]))] for fam in families}

    tried: set[tuple] = set()

    def run(groups) -> dict:
        """묶음들 → 교차검증 점수 (같은 조합은 한 번만 돌린다. 묶음은 늘 정해진 순서로 넣는다)."""
        groups = tuple(expand(groups))
        tried.add(cv.key(groups))
        return cv.run(groups)[1]

    # 1) 분야 단위
    combos = [c for r in range(len(families) + 1) for c in combinations(families, r)]
    scores = {c: run([g for fam in c for g in present[fam]]) for c in combos}
    picked = pick_combo(scores, fam_varies)
    chosen = {fam: list(present[fam]) if fam in picked else [] for fam in families}

    # 2) 분야 안의 묶음 단위 (묶음이 둘 이상인 분야만)
    basis: dict[str, tuple] = {}                       # 묶음 → (넣기 전 점수, 넣은 뒤 점수, 센 구간): 이유 문장의 재료
    whole: set[str] = set()                            # 혼자서는 못 넘지만 분야 전체로 넘어 함께 쓰는 분야
    for fam in families:
        parts = present[fam]
        without = tuple(f for f in picked if f != fam)
        if len(parts) < 2:
            basis[parts[0]] = (scores[without], scores[tuple(f for f in families if f in picked or f == fam)], fam_varies[fam])
            continue
        rest = [g for f in families if f != fam for g in chosen[f]]
        sel: list[str] = []
        while True:
            base = run(rest + sel)
            trials = {g: run(rest + sel + [g]) for g in parts if g not in sel}
            for g, after in trials.items():
                basis[g] = (base, after, varies[g])    # 떨어진 묶음은 마지막으로 넣어 본 때의 비교가 남는다
            passed = [g for g, after in trials.items() if beats(after, base, varies[g])[0]]
            if not passed:
                break
            sel.append(min(passed, key=lambda g: trials[g]["wape"]))
        if sel:
            chosen[fam] = sel
        elif fam in picked:                            # 함께일 때만 나오는 효과 → 분야 전체를 그대로 쓴다
            whole.add(fam)
            for g in parts:
                basis[g] = (run(rest), run(rest + parts), fam_varies[fam])

    adopted = expand([g for fam in families for g in chosen[fam]])
    family_of = {g: fam for fam, parts in SIGNAL_FAMILIES.items() for g in parts}
    decisions = []                                     # 묶음마다 이유: 그 묶음을 넣었을 때 vs 뺐을 때
    for group in SIGNAL_GROUPS:
        if group in flat:
            decisions.append(decide(group, signals_in([group], frame), None, None,
                                    note="자료는 있지만 검증 기간에 값이 한 번도 바뀌지 않아 효과를 평가할 수 없음"))
        elif group not in has_data:
            decisions.append(decide(group, [], None, None))
        else:
            before, after, mask = basis[group]
            fam = family_of[group]
            decisions.append(decide(group, signals_in([group], frame), before, after, adopted=group in adopted,
                                    together=fam if fam in whole else None, mask=mask))
    return adopted, decisions, len(tried)


# ---------------------------------------------------------------- 3. 화면용 비교표

def comparison_table(cv: CrossValidator, cv_m0: pd.DataFrame, adopted: list[str]) -> list[dict]:
    """M0 + 기본 정의의 M1·M2·M3 점수 (+ 채택 조합이 그중에 없으면 따로 한 줄)."""
    table, seen = [score(cv_m0, "M0")], set()
    for name in ["M1", "M2", "M3"]:
        key = cv.key(FEATURE_SETS[name])
        if key not in seen:                            # 신호 자료가 없어 앞 모델과 같으면 생략
            seen.add(key)
            preds = cv.run(FEATURE_SETS[name])[0]
            table.append(score(preds, name) | dict(days_won=days_won(preds, cv_m0)))
    if cv.key(adopted) not in seen:
        preds = cv.run(adopted)[0]
        table.append(score(preds, f"{model_label(adopted)}(채택 신호만)") | dict(days_won=days_won(preds, cv_m0)))
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
    mine = score(t_final, chosen) | dict(days_won=days_won(t_final, t_m0))
    return [score(t_m0, "M0"), mine], effect, int(t_m0["sold_out"].astype(bool).sum())


# ---------------------------------------------------------------- 6. 설명 문장

def data_note(plan: FoldPlan, n_combos: int, adopted: list[str], cv_m0: pd.DataFrame, chosen_cv: pd.DataFrame,
              n_sold_out: int, calibration_reason: str) -> str:
    """화면과 발표에서 그대로 밝힐 설명: 기록 길이, 고른 신호, 기준선 대비 개선과 그 확실함, 품절 제외, 범위 보정."""
    chosen = model_label(adopted)
    notes = [plan.note]
    if n_combos > 1:
        picked = ", ".join(GROUP_LABELS.get(g, g) for g in adopted) or "신호 없음"
        notes.append(f"신호 조합 {n_combos}가지를 비교해 '{picked}' 선택")
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
                 close_time: str = DEFAULT_CLOSE_TIME, prices: dict[str, float] | None = None,
                 **model_kwargs) -> BacktestResult:
    """매장 하나의 판매(+신호) → BacktestResult.  model_kwargs는 테스트용 (예: iterations=30).
    prices = {메뉴: 판매가(원)} 를 주면 남거나 모자란 개수를 금액으로도 환산한다 (ModelScore.amount). 예측에는 쓰지 않는다."""
    store_ids = sales["store_id"].unique()
    if len(store_ids) != 1:
        raise ValueError(f"매장 하나씩 평가합니다. 받은 매장: {list(store_ids)}")
    store_id = str(store_ids[0])

    names = []
    if signals is not None:
        signals = signals[signals["store_id"] == store_id]
        names = available_signals(SIGNAL_GROUPS, signals)
    frame = build_frame(sales, signals, names, close_time=close_time)
    if prices:
        frame["price"] = frame["menu"].map(prices)

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
