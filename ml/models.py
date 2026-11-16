"""예측 모델: M0(기준선) + CatBoost M1~M3.

모든 모델은 같은 모양으로 쓴다:
    model = make_model("M1").fit(train_frame)
    out = model.predict(frame)      # DataFrame[p10, p40, p50, p60, p80, p90, pred], frame과 같은 index
                                    # pred = p50 (예상 판매량)

- M0  지난주 같은 요일 그대로. 사장님 감과 비슷한 수준 → 이걸 못 이기면 모델이 의미 없다
- M1  CatBoost, 판매 이력·달력 변수만
- M2  M1 + 날씨
- M3  M2 + 학사일정·행사·유행
  (M1~M3은 같은 코드이고, 쓰는 변수 목록만 features.FEATURE_SETS에서 다르게 받는다)
"""
import numpy as np
import pandas as pd
from catboost import CatBoostRegressor

from ml.features import CATEGORICAL_FEATURES, SIGNAL_GROUPS, base_level, feature_columns  # base_level은 다른 파일이 models에서도 가져다 씀

# p40·p50·p80 = 준비 방식(폐기 줄이기·균형·품절 줄이기), p10·p90 = 화면의 예상 범위, p60 = 범위 보정용
QUANTILES = [0.1, 0.4, 0.5, 0.6, 0.8, 0.9]
Q_COLS = ["p10", "p40", "p50", "p60", "p80", "p90"]
SHORT_DATA_DAYS = 120          # 학습 기간이 이보다 짧으면 '짧은 데이터 모드' (더 단순한 모델)




def _finalize(q: np.ndarray, index) -> pd.DataFrame:
    """분위 예측 정리: 0 미만은 0으로, 분위가 뒤집히면(p10 > p50 등) 정렬해서 바로잡는다."""
    q = np.sort(np.clip(q, 0, None), axis=1)
    out = pd.DataFrame(q, columns=Q_COLS, index=index)
    out["pred"] = out["p50"]
    return out


class BaselineM0:
    """지난주 같은 요일 판매량을 그대로 내일 예측으로 쓴다. 학습할 것이 없다."""
    name = "M0"

    def fit(self, train: pd.DataFrame) -> "BaselineM0":
        return self

    def predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        # 예측값: lag_7 → (없으면) 4주 같은 요일 평균 → (없으면) 최근 7일 평균 → (없으면) 0
        p50 = frame["lag_7"].fillna(frame["same_wd_mean_4"]).fillna(frame["mean_7"]).fillna(0.0)
        # 범위: 지난 4주 같은 요일의 최소~최대 (같은 요일 기록이 없으면 범위 없이 p50 하나)
        p10 = frame["same_wd_min_4"].fillna(p50)
        p90 = frame["same_wd_max_4"].fillna(p50)
        # 사이 분위는 분위 간격대로 직선으로 채운다: p40은 p50→p10의 1/4 지점, p60·p80은 p50→p90의 1/4·3/4 지점
        p40 = p50 - (p50 - p10) * 0.25
        p60 = p50 + (p90 - p50) * 0.25
        p80 = p50 + (p90 - p50) * 0.75
        return _finalize(np.column_stack([p10, p40, p50, p60, p80, p90]), frame.index)


class CatBoostQuantile:
    """CatBoost 하나로 모든 매장·메뉴를 함께 학습하고, 다섯 분위를 한 번에 예측한다.

    목표는 판매량 자체가 아니라 '평소 대비 비율'이다:
        base = mean_28 → mean_7 → lag_1 (처음으로 값이 있는 것), 1 미만이면 1
        y    = qty / base           예: 평소 50개 팔리는데 60개 → 1.2
        예측 = (비율 예측) × base
    이렇게 하면 하루 60개짜리 소금빵과 10개짜리 식빵을 한 모델이 같은 '비율' 단위로 배운다.

    시드만 다른 모델 3개를 학습해 평균한다 (11/15). 시드 하나만 바꿔도 검증 WAPE가 0.275~0.285로 흔들리고
    신호 채택이 뒤집혔다. 3개 평균이면 시작 시드 4가지에서 채택이 모두 같았다 (시간은 약 2.5배).
    """

    # 기본 설정 (11/13 결정): TASKS.md의 500개·depth 6·lr 0.05보다 약 6배 빠르고, 처음 보는 기간에서
    # WAPE는 비슷하며 과적합(범위가 너무 좁아지는 문제)이 덜했다. 실험은 가상 데이터 기준이므로
    # 실제 데이터 결과를 보고 숫자를 맞추려고 다시 고르지 않는다 (TASKS.md §6).
    DEFAULT = dict(iterations=150, depth=4)
    SHORT = dict(iterations=100, depth=4)       # 짧은 데이터 모드 (학습 120일 미만)

    def __init__(self, name: str = "M1", groups=None, iterations: int | None = None, depth: int | None = None,
                 learning_rate: float = 0.1, random_seed: int = 0, short: bool | None = None,
                 n_seeds: int = 3):
        self.name = name
        self.groups = groups                    # 신호 묶음 목록. None이면 이름(M1~M3)의 기본 묶음
        self.iterations, self.depth = iterations, depth
        self.learning_rate, self.random_seed = learning_rate, random_seed
        self.short = short
        self.n_seeds = n_seeds                  # 시드만 다른 모델 n개의 평균 (우연한 흔들림 줄이기)

    _base = staticmethod(base_level)

    def fit(self, train: pd.DataFrame) -> "CatBoostQuantile":
        self.features = feature_columns(self.name, train, self.groups)
        self.signal_cols = [c for c in self.features if c in {n for v in SIGNAL_GROUPS.values() for n in v}]

        usable = train["qty"].notna()
        sold_out = train["sold_out"].astype("boolean").fillna(False).astype(bool)
        self.n_dropped_sold_out = int((usable & sold_out).sum())
        # 메뉴 첫날은 과거 판매가 없어 base가 1이 되고 비율이 판매량 그대로(예: 50배)가 되므로 뺀다
        has_base = train[["mean_28", "mean_7", "lag_1"]].notna().any(axis=1)
        self.n_dropped_no_base = int((usable & ~sold_out & ~has_base).sum())
        rows = train[usable & ~sold_out & has_base]         # ★ 품절일은 정답이 '수요의 하한'일 뿐이라 학습에서 뺀다

        n_days = rows["date"].nunique()
        short = self.short if self.short is not None else n_days < SHORT_DATA_DAYS
        preset = self.SHORT if short else self.DEFAULT
        iterations = self.iterations or preset["iterations"]
        depth = self.depth or preset["depth"]

        X = rows[self.features]
        y = rows["qty"] / self._base(rows)
        self.models = [CatBoostRegressor(
            loss_function="MultiQuantile:alpha=" + ",".join(map(str, QUANTILES)),
            iterations=iterations, depth=depth, learning_rate=self.learning_rate,
            random_seed=self.random_seed + k, cat_features=[c for c in CATEGORICAL_FEATURES if c in self.features],
            # 범주(메뉴 등)가 255개 이하면 원-핫 인코딩. CatBoost 기본 방식(target statistics)보다
            # 이 데이터에서 약 12배 빠르고 정확도는 같았다 (메뉴 11개, 매장 1개).
            one_hot_max_size=255,
            verbose=False, allow_writing_files=False,
        ).fit(X, y) for k in range(self.n_seeds)]

        # 학습 기간 신호의 중앙값 = '평소 값' (나중에 예측 근거를 계산할 때 비교 기준으로 씀)
        self.signal_medians = rows[self.signal_cols].median().to_dict()
        self.n_train, self.n_train_days, self.short_mode = len(rows), n_days, short
        return self

    def predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        X = frame[self.features]
        ratio = np.mean([m.predict(X) for m in self.models], axis=0)   # (행 수, 5) 비율 예측, 시드 평균
        q = ratio * self._base(frame).to_numpy()[:, None]   # 비율 × 평소 수준 = 판매량
        return _finalize(q, frame.index)


def make_model(name: str, **kwargs):
    """"M0" → BaselineM0, "M1"/"M2"/"M3" → CatBoostQuantile."""
    if name == "M0":
        return BaselineM0()
    return CatBoostQuantile(name, **kwargs)
