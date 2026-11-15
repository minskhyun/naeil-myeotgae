"""가상 데이터 생성기가 계약 형식과 '시점 규칙'을 지키는 데이터를 만드는지 확인한다."""
import pandas as pd

from ml.sample_data import MENUS, generate


def test_generate_writes_valid_files(tmp_path):
    generate(tmp_path, seed=1)
    for name in ["pos_raw.csv", "sales.csv", "signals.csv", "store.json", "truth.json", "demand_true.csv"]:
        assert (tmp_path / name).exists(), name

    sales = pd.read_csv(tmp_path / "sales.csv", parse_dates=["date"])
    sig = pd.read_csv(tmp_path / "signals.csv", parse_dates=["date", "published_at"])

    # 품절은 굽는 개수(cap)가 있는 메뉴에서만 생긴다
    no_cap = [m for m, v in MENUS.items() if "cap" not in v]
    assert not sales.loc[sales["menu"].isin(no_cap), "sold_out"].any()
    assert sales["sold_out"].any()

    # 예보는 그날 전에, 관측은 그날이 끝난 뒤에 공개된다
    fc, obs = sig[sig["kind"] == "forecast"], sig[sig["kind"] == "observed"]
    assert (fc["published_at"] < fc["date"]).all()
    assert (obs["published_at"] > obs["date"] + pd.Timedelta(days=1)).all()

    # 같은 날짜·신호에 예보가 두 번(이틀 전, 하루 전) 있다 → '가장 늦게 공개된 값' 규칙을 시험할 수 있다
    n_versions = fc.groupby(["date", "signal"]).size()
    assert (n_versions == 2).all()

    # 당일에야 공지된 행사가 있다 → 누수 규칙이 이걸 걸러야 한다
    ev = sig[sig["signal"] == "nearby_event"]
    assert (ev["published_at"] > ev["date"]).any()
