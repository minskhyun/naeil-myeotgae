"""ml/shared.py 테스트: 다른 매장과 함께 배우기 (공유 모델과 내 매장 모델을 섞기).

한 표에 다른 매장의 줄을 이어 붙여 한 모델이 배우고(내 줄 무게 1, 다른 매장 줄 0.5), 내 기록만으로 배운 모델보다
검증에서 나을 때만 쓴다. 켠 매장끼리만 섞는다.
"""
import json
from pathlib import Path

import pandas as pd
import pytest

from contracts.schemas import BacktestResult, SharedLearning, StoreConfig
from ml import shared
from ml.evaluate import cross_val_predict, plan_folds, run_backtest
from ml.features import build_frame, load_sales
from ml.predict import predict_from_backtest

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample" / "sinchon-a"


def _days(sales, first, n):
    """판매 기록에서 first일째부터 n일치."""
    start = sales["date"].min() + pd.Timedelta(days=first)
    return sales[(sales["date"] >= start) & (sales["date"] < start + pd.Timedelta(days=n))]


@pytest.fixture(scope="module")
def stores():
    """내 매장(기록 70일) + 함께 배울 매장(같은 기간 150일, 메뉴 구성이 조금 다름)."""
    sales = load_sales(SAMPLE / "sales.csv")
    mine = _days(sales, 80, 70)
    other = _days(sales, 0, 150).assign(store_id="partner-b")
    other = other[other["menu"] != "식빵"]                                      # 내 매장에만 있는 메뉴
    other = pd.concat([other, other[other["menu"] == "소금빵"].assign(menu="잠봉뵈르")])   # 그 매장에만 있는 메뉴
    return mine, [(other, None, "21:00")]


def test_pooled_table_and_weights(stores):
    mine, partners = stores
    frame = build_frame(mine)
    both = shared.pooled(frame, partners, [])
    assert set(both["store_id"]) == {"sinchon-a", "partner-b"}                  # 메뉴 구성이 달라도 한 표가 된다
    assert both.groupby("store_id")["weight"].first().to_dict() == {"sinchon-a": 1.0, "partner-b": shared.PARTNER_WEIGHT}
    assert list(both.columns) == list(frame.columns) + ["weight"]              # 열은 그대로, 줄만 늘어난다
    assert len(shared.mine(both, "sinchon-a")) == len(frame)


def test_time_rule_holds_for_partner_rows(stores):
    """다른 매장의 줄도 검증 구간보다 앞선 것만 학습에 쓰인다."""
    mine, partners = stores
    both = shared.pooled(build_frame(mine), partners, [])
    folds = plan_folds(mine["date"]).folds
    preds = cross_val_predict(both, "M1", folds, groups=[], iterations=20)
    for k, (start, _end) in enumerate(folds):
        assert preds.loc[preds["fold"] == k, "train_last"].max() < start


def test_backtest_compares_shared_with_own(stores, tmp_path):
    mine, partners = stores
    alone = run_backtest(mine, iterations=30)
    assert alone.shared is None                                                # 함께 배울 매장이 없으면 판정도 없다
    together = run_backtest(mine, partners=partners, iterations=30)
    s = together.shared
    assert isinstance(s, SharedLearning) and s.partners == 1 and s.weight == shared.PARTNER_WEIGHT
    assert s.wape_own == pytest.approx(next(x.wape for x in alone.cv_scores if x.model == "M1"), abs=1e-4)   # 같은 '내 모델'과 비교
    assert s.adopted == (s.wape_shared <= s.wape_own * 0.97 and "사용함" in s.reason)   # 3% 이상 나을 때만 (과반 구간 조건도 있음)
    assert s.reason in together.data_note and together.store_id == "sinchon-a"
    assert BacktestResult.model_validate_json(together.model_dump_json()) == together   # 저장했다 읽어도 같다

    forecast = predict_from_backtest(mine, None, together, partners=partners, iterations=30)
    assert forecast.store_id == "sinchon-a" and "잠봉뵈르" not in {r.menu for r in forecast.rows}   # 예측은 내 매장 메뉴만


def test_prediction_uses_partners_only_when_adopted(stores, monkeypatch):
    mine, partners = stores
    bt = run_backtest(mine, partners=partners, iterations=30)
    seen = []
    real = shared.pooled
    monkeypatch.setattr(shared, "pooled", lambda *a, **k: seen.append(1) or real(*a, **k))
    for adopted in (False, True):
        bt.shared.adopted = adopted
        predict_from_backtest(mine, None, bt, partners=partners, iterations=20)
    assert len(seen) == 1                                                      # 채택됐을 때만 다른 매장 기록을 쓴다


def test_partners_are_only_stores_that_opted_in(tmp_path):
    """run.py: 이 매장이 '함께 배우기'를 켰을 때만, 같은 설정을 켠 다른 매장과."""
    import run
    sales = _days(load_sales(SAMPLE / "sales.csv"), 0, 30)

    def make(store_id, share, with_sales=True):
        folder = tmp_path / store_id
        folder.mkdir()
        StoreConfig(store_id=store_id, share_learning=share).write(folder / "store.json")
        if with_sales:
            sales.assign(store_id=store_id).to_csv(folder / "sales_clean.csv", index=False)
        return folder

    me = make("me", True)
    make("joined", True)
    make("not-joined", False)
    make("no-data-yet", True, with_sales=False)
    found = run._partners(StoreConfig.read(me / "store.json"), me)
    assert [p[0]["store_id"].iloc[0] for p in found] == ["joined"]
    StoreConfig(store_id="me", share_learning=False).write(me / "store.json")   # 내가 끄면 아무와도 섞지 않는다
    assert run._partners(StoreConfig.read(me / "store.json"), me) == []
    assert json.loads((me / "store.json").read_text(encoding="utf-8"))["share_learning"] is False
