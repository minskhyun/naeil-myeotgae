"""ml/metrics.py 테스트: 화면에 보여 주는 '남거나 모자란 개수'와 금액 환산. (비율 지표는 tests/test_backtest.py)"""
import pandas as pd

from ml.metrics import miss_counts


def test_miss_counts_and_amount():
    """남거나 모자란 개수(비율이 아니라 개수)와 판매가 환산."""
    d = pd.DataFrame(dict(date=pd.to_datetime(["2026-10-01", "2026-10-01", "2026-10-02"]), qty=[10, 2, 5], pred=[13, 1, 5]))
    assert miss_counts(d) == dict(over=3.0, under=1.0, days=2)                       # 3개 남고 1개 모자람, 이틀
    priced = d.assign(price=[3000, 5000, None])
    assert miss_counts(priced)["amount"] == 3 * 3000 + 1 * 5000                      # 판매가를 모르는 메뉴는 0원으로
