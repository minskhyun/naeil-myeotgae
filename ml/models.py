"""예측 모델: M0(기준선) + CatBoost M1~M3.

모든 모델은 같은 모양으로 쓴다:
    model = make_model("M1").fit(train_frame)
    out = model.predict(frame)      # DataFrame[p10, p40, p50, p60, p80, p90, pred], frame과 같은 index
                                    # pred = 예상 판매량. M0은 p50, CatBoost는 평균(기대값)
                                    # CatBoost의 분위는 평균 둘레 확률 분포(음이항)의 분위

- M0  지난주 같은 요일 그대로. 사장님 감과 비슷한 수준 → 이걸 못 이기면 모델이 의미 없다
- M1  CatBoost, 판매 이력·달력 변수만
- M2  M1 + 날씨
- M3  M2 + 학사일정·행사·유행
  (M1~M3은 같은 코드이고, 쓰는 변수 목록만 features.FEATURE_SETS에서 다르게 받는다)
"""
import numpy as np
import pandas as pd
from catboost import CatBoostRegressor
from scipy import stats

from ml.features import ALL_SIGNALS, CATEGORICAL_FEATURES, base_level, feature_columns

# p40·p50·p80 = 준비 방식(폐기 줄이기·균형·품절 줄이기), p10·p90 = 화면의 예상 범위, p60 = 범위 보정용
QUANTILES = [0.1, 0.4, 0.5, 0.6, 0.8, 0.9]
Q_COLS = ["p10", "p40", "p50", "p60", "p80", "p90"]
SHORT_DATA_DAYS = 120          # 판매 기록이 이보다 짧으면 '짧은 데이터 모드' (더 단순한 모델, 더 짧은 검증 구간)
SPREAD_DAYS = 28               # 퍼짐(판매가 평균에서 얼마나 흩어지나)을 재는 데 쓰는 마지막 며칠 (기록이 짧으면 3분의 1)
SPREAD_MIN_DAYS = 5
SPREAD_RANGE = (1.0, 1000.0)   # 퍼짐 값 k의 허용 범위 (작을수록 넓게 퍼진다. 1000 이상은 포아송과 같다)


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
    """CatBoost 하나로 모든 메뉴를 함께 학습해 예상 판매량(평균)을 예측하고, 그 둘레의 확률 분포에서 분위를 꺼낸다.

    범위(분위)를 만드는 방법 (11/20 바꿈): 분위마다 따로 배우는 대신 **판매 개수의 확률 분포**를 쓴다.
        판매 개수 ~ 음이항 분포(평균 = 모델의 예측, 퍼짐 k = 이 매장에서 잰 값 하나)
        p10 … p90 = 그 분포의 10% … 90% 지점
    전에는 여섯 분위를 각각 배우는 모델(MultiQuantile)을 따로 뒀다. 기록이 짧으면 양 끝 분위를 배울 자료가 모자라
    범위가 좁게 나왔고(가상 매장·공개 데이터에서 실제 판매의 75%쯤만 범위 안, 목표 80%), 평균 모델과 어긋나
    예상값이 범위 끝에 붙기도 했다. 바꾼 뒤 같은 기간에서 81~84% (REVIEW E 11/20).
    분포 방식은 '퍼짐' 숫자 하나만 재면 되고, 평균과 범위가 한 분포에서 나와 어긋나지 않는다.
    ★ 가정: 판매 개수가 음이항 분포를 따른다 (개수 자료에 흔히 쓰는 분포. 평균이 커질수록 분산이 더 빨리 커진다).
      가정이 맞지 않는 매장에서는 범위가 틀릴 수 있다 → 범위 적중률(coverage_80)을 매장마다 검증해 보여 준다.

    목표는 판매량 자체가 아니라 '평소 대비 비율'이다:
        base = mean_28 → mean_7 → lag_1 (처음으로 값이 있는 것), 1 미만이면 1
        y    = qty / base           예: 평소 50개 팔리는데 60개 → 1.2
        예측 = (비율 예측) × base
    이렇게 하면 하루 60개짜리 소금빵과 10개짜리 식빵을 한 모델이 같은 '비율' 단위로 배운다.

    예상 판매량(pred)은 중앙값(p50)이 아니라 **평균(기대값)** 이다 (11/19). 평균을 배우는 모델(RMSE)을 따로 둔다.
    하루에 0~2개 팔리는 메뉴는 중앙값이 0이라, 그런 메뉴가 많은 매장에서는 중앙값의 합이 실제 판매의 절반밖에
    안 됐다 (첫 실매장: 주말 합계 −54%, 평균으로 바꾸면 −19% = 지난주 같은 요일 방식과 같은 수준).
    많이 팔리는 메뉴는 평균과 중앙값이 거의 같아 달라지는 것이 없다.

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

    def fit(self, train: pd.DataFrame) -> "CatBoostQuantile":
        self.features = feature_columns(self.name, train, self.groups)
        self.signal_cols = [c for c in self.features if c in ALL_SIGNALS]     # 근거 문장을 만들 때 쓴다 (predict.py)

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

        def train_means(data: pd.DataFrame) -> list[CatBoostRegressor]:
            """평균(기대값)을 배우는 모델을 시드만 바꿔 n_seeds개."""
            X, y = data[self.features], data["qty"] / base_level(data)
            return [CatBoostRegressor(
                loss_function="RMSE", iterations=iterations, depth=depth, learning_rate=self.learning_rate,
                random_seed=self.random_seed + k, cat_features=[c for c in CATEGORICAL_FEATURES if c in self.features],
                # 범주(메뉴 등)가 255개 이하면 원-핫 인코딩. CatBoost 기본 방식(target statistics)보다
                # 이 데이터에서 약 12배 빠르고 정확도는 같았다 (메뉴 11개, 매장 1개).
                one_hot_max_size=255,
                verbose=False, allow_writing_files=False,
            ).fit(X, y) for k in range(self.n_seeds)]

        self.spread = self._fit_spread(rows, train_means)       # 범위의 넓이 (학습 기간 안에서만 잰다)
        self.mean_models = train_means(rows)                    # 예상 판매량(평균)
        self.n_train, self.short_mode = len(rows), short
        return self

    def _mean(self, models, frame: pd.DataFrame) -> np.ndarray:
        """평균 예측 (판매량 단위, 0 이상) = 비율 예측의 시드 평균 × 평소 수준."""
        ratio = np.mean([m.predict(frame[self.features]) for m in models], axis=0)
        return np.clip(ratio * base_level(frame).to_numpy(), 0, None)

    def _fit_spread(self, rows: pd.DataFrame, train_means) -> float:
        """판매가 예측 평균에서 얼마나 흩어지는지 = 음이항 분포의 k.  분산 = 평균 + 평균² / k.

        학습 기간의 마지막 며칠을 떼어 놓고, 그 앞의 기록만으로 배운 모델이 그 며칠을 얼마나 틀렸는지로 잰다.
        (다 본 날을 다시 맞히게 하면 오차가 작게 나와 범위가 좁아진다. 떼어 놓은 날은 모델이 처음 보는 날이다.)
        식: k = Σ평균² ÷ Σ((실제 − 평균)² − 평균).  분모가 0 이하면 포아송만큼만 흩어진 것 → k를 최대로.
        """
        days = np.sort(rows["date"].unique())
        hold = max(SPREAD_MIN_DAYS, min(SPREAD_DAYS, len(days) // 3))
        if len(days) - hold >= SPREAD_MIN_DAYS:
            cut = days[-hold]
            past, recent = rows[rows["date"] < cut], rows[rows["date"] >= cut]
            mu = self._mean(train_means(past), recent)
        else:                                                   # 기록이 너무 짧다 (테스트용 작은 표): 본 날로 잰다
            recent, mu = rows, self._mean(train_means(rows), rows)
        y = recent["qty"].to_numpy(float)
        extra = float(np.sum((y - mu) ** 2 - mu))               # 포아송보다 더 흩어진 만큼
        k = float(np.sum(mu ** 2)) / extra if extra > 0 else SPREAD_RANGE[1]
        return float(np.clip(k, *SPREAD_RANGE))

    def predict_mean(self, frame: pd.DataFrame) -> np.ndarray:
        """예상 판매량(평균)만. 근거 계산(predict.explain)처럼 범위가 필요 없을 때 쓴다."""
        return self._mean(self.mean_models, frame)

    def predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        mean = self.predict_mean(frame)
        mu = np.clip(mean, 1e-3, None)
        k = self.spread
        # 분위 = 평균이 mu이고 퍼짐이 k인 음이항 분포의 분위 (개수라서 정수)
        q = np.column_stack([stats.nbinom.ppf(tau, k, k / (k + mu)) for tau in QUANTILES])
        out = _finalize(q, frame.index)
        out["pred"] = mean                                      # 예상 판매량 = 평균
        # 아주 조금 팔리는 메뉴는 분위가 0뿐일 수 있다 (평균 0.3개 → 90% 지점도 0). 범위는 평균을 품게 한다
        out["p10"], out["p90"] = np.minimum(out["p10"], mean), np.maximum(out["p90"], mean)
        return out


def make_model(name: str, **kwargs):
    """"M0" → BaselineM0, "M1"/"M2"/"M3" → CatBoostQuantile."""
    if name == "M0":
        return BaselineM0()
    return CatBoostQuantile(name, **kwargs)
