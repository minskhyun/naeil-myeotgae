"""ingest.py 테스트: POS 형식 읽기, 메뉴명 통일 후보, 휴무·0개·품절 처리, 전체 실행."""
import json
from pathlib import Path

import pandas as pd
import pytest

from ml.ingest import (clean_sales, ingest_store, read_pos, sold_out_evidence, suggest_menu_merges,
                       temp_tag, _parse_dates)
from run import main as run_main

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"
SAMPLE = ROOT / "data" / "sample" / "sinchon-a"


# ---------------------------------------------------------------- 읽기

@pytest.fixture(scope="module")
def expected():
    return (pd.read_csv(FIX / "expected_daily.csv", parse_dates=["날짜"])
            .rename(columns={"날짜": "date", "메뉴명": "menu_raw", "판매수량": "qty"})[["date", "menu_raw", "qty"]])


@pytest.mark.parametrize("name, pos_type, receipt", [
    ("toss_receipts.xlsx", "toss", True),       # 제목 2줄, 영수증 단위, 결제일시에 시각, 합계·취소 행
    ("okpos_daily.xlsx", "okpos", False),       # 제목·빈 줄, 영업일자 20251101 숫자, 합계 행
    ("okpos_daily_cp949.csv", "okpos", False),  # 같은 내용의 cp949 CSV
])
def test_read_pos_fixtures(expected, name, pos_type, receipt):
    df, log = read_pos(FIX / name)                                  # auto: 형식·머리글 줄을 스스로 찾음
    assert log["pos_type"] == pos_type and log["header_row"] == 2 and log["receipt_level"] is receipt
    assert log["dropped_total_or_blank"] == 1                       # 합계 행
    m = expected.merge(df, on=["date", "menu_raw"], how="outer", suffixes=("_e", "_r"))
    assert (m["qty_e"] == m["qty_r"]).all()                         # 날짜·메뉴별 수량이 정답과 모두 같음
    if receipt:
        assert log["dropped_cancel"] == 1 and {"first_time", "last_time"} <= set(df.columns)


def test_item_sales_workbook_with_monthly_sheets(tmp_path):
    """상품별 매출 엑셀: 열 이름이 '품목명', 달마다 시트가 따로. 금액권·충전은 메뉴가 아니므로 뺀다."""
    head = ["일자", "품목코드", "품목명", "규격", "수량", "공급가액", "부가세"]
    sep = pd.DataFrame([head, [20260929, "00001", "아메리카노 (Americano)", "수량", 120, 360000, 36000],
                        [20260929, "00380", "충전(Charge)", "수량", 2, 4000, 400],
                        [20260930, "00001", "아메리카노 (Americano)", "수량", 0, 0, 0]])
    octo = pd.DataFrame([head, [20261001, "00001", "아메리카노 (Americano)", "수량", 122, 366000, 36600],
                         [20261001, "00210", "10000원 ", "수량", 3, 30000, 3000],
                         [20261001, "00044", "소금빵 (Salt bread)", "수량", 4, 12000, 1200]])
    memo = pd.DataFrame([["메모"], ["이 시트는 표가 아님"]])
    p = tmp_path / "items.xlsx"
    with pd.ExcelWriter(p) as w:
        for name, sheet in (("9월", sep), ("10월", octo), ("메모", memo)):
            sheet.to_excel(w, sheet_name=name, header=False, index=False)
    df, log = read_pos(p)
    assert log["pos_type"] == "items" and log["sheets"] == 2                 # 머리글이 같은 두 시트만 이어 읽음
    assert log["non_menu"] == ["10000원", "충전(Charge)"] and log["dropped_non_menu"] == 2
    got = {(d.strftime("%m-%d"), m): q for d, m, q in df[["date", "menu_raw", "qty"]].itertuples(index=False)}
    assert got == {("09-29", "아메리카노 (Americano)"): 120, ("09-30", "아메리카노 (Americano)"): 0,
                   ("10-01", "아메리카노 (Americano)"): 122, ("10-01", "소금빵 (Salt bread)"): 4}


def test_header_not_found_gives_hint(tmp_path):
    p = tmp_path / "weird.csv"
    p.write_text("거래번호,품목,개수\n1,소금빵,3\n", encoding="utf-8")
    with pytest.raises(ValueError, match="COLUMN_MAP"):
        read_pos(p)


def test_parse_dates_variants():
    s = pd.Series(["2026-10-01", "2026.10.02", "2026/10/03", "20261004", "20261005.0", "2026-10-06 13:05:00", "합계"])
    out = _parse_dates(s)
    assert out[:5].dt.day.tolist() == [1, 2, 3, 4, 5]
    assert out[5] == pd.Timestamp("2026-10-06 13:05") and pd.isna(out[6])


# ---------------------------------------------------------------- 메뉴명 통일 후보

def test_temp_tag():
    assert [temp_tag(m) for m in ["아이스 아메리카노", "아메리카노(ICE)", "카페라떼(HOT)", "따뜻한 라떼", "소금빵"]]         == ["ICE", "ICE", "HOT", "HOT", "-"]


def test_suggest_menu_merges():
    menus = ["아메리카노(ICE)", "아이스 아메리카노", "아메리카노(HOT)", "소금빵", "소금 빵", "크루아상", "크로와상", "베이글"]
    pairs = {(a, b): s for a, b, s in suggest_menu_merges(menus)}
    assert pairs[("아메리카노(ICE)", "아이스 아메리카노")] == 1.0     # 표기만 다른 같은 메뉴
    assert pairs[("소금 빵", "소금빵")] == 1.0
    assert ("크로와상", "크루아상") in pairs                          # 철자 차이
    assert not any("HOT" in a + b and ("ICE" in a + b or "아이스" in a + b) for a, b in pairs)   # ICE↔HOT은 후보 아님
    assert not any("베이글" in a + b for a, b in pairs)
    assert suggest_menu_merges(["딸기 케이크 4인", "딸기 케이크 6인", "TARTE FRUITS 4P", "TARTE FRUITS 6P"]) == []   # 크기 차이


# ---------------------------------------------------------------- 정리

def test_sold_out_evidence():
    capped = pd.Series([80] * 13 + [79] * 2 + [78] + [70] * 20)    # 80에 쌓임 → 품절
    tail = pd.Series([21] * 4 + [20] * 2 + [19] * 3 + [18] * 2 + [15] * 20)   # 자연스러운 꼬리 → 아님
    small = pd.Series([4] * 5 + [2] * 20)                             # 4개뿐인 메뉴 → 아님
    assert sold_out_evidence(capped)["sold_out"] is True
    assert sold_out_evidence(tail)["sold_out"] is False
    assert sold_out_evidence(small)["sold_out"] is False


def test_clean_sales_zero_fill_closed_day_and_menu_map():
    d = pd.Timestamp
    pos = pd.DataFrame({
        "date": [d("2026-10-01"), d("2026-10-01"), d("2026-10-02"), d("2026-10-04"), d("2026-10-04")],
        "menu_raw": ["소금빵", "아메리카노(ICE)", "소금빵", "소금빵", "아이스 아메리카노"],
        "qty": [10, 5, 12, 9, 7],
    })                                                               # 10/03은 기록 없음 = 휴무
    sales, log = clean_sales(pos, "test", {"아메리카노(ICE)": "아이스 아메리카노"})
    assert log["closed_days"] == ["2026-10-03"]
    got = {(str(r.date.date()), r.menu): r.qty for r in sales.itertuples()}
    assert got == {("2026-10-01", "소금빵"): 10, ("2026-10-01", "아이스 아메리카노"): 5,
                   ("2026-10-02", "소금빵"): 12, ("2026-10-02", "아이스 아메리카노"): 0,   # POS에 없던 0개 판매
                   ("2026-10-04", "소금빵"): 9, ("2026-10-04", "아이스 아메리카노"): 7}


def test_ingest_sample_matches_truth(tmp_path):
    """가상 매장의 POS 원본 → 정리 결과가 sales.csv(정답)와 같은가: 수량·품절 모두."""
    (tmp_path / "menu_map.json").write_text(json.dumps({"아메리카노(ICE)": "아이스 아메리카노"}), encoding="utf-8")
    ingest_store(SAMPLE / "pos_raw.csv", "sinchon-a", tmp_path)
    got = pd.read_csv(tmp_path / "sales_clean.csv", parse_dates=["date"])
    truth = pd.read_csv(SAMPLE / "sales.csv", parse_dates=["date"])
    m = truth.merge(got, on=["date", "menu"], how="left", suffixes=("_t", "_g"), indicator=True)
    missing = m[m["_merge"] == "left_only"]
    assert (missing["qty_t"] == 0).all() and len(missing) <= 1      # 첫날 0개(POS에 없음)만 빠질 수 있음
    both = m[m["_merge"] == "both"]
    assert (both["qty_t"] == both["qty_g"]).all()
    assert (both["sold_out_t"] == both["sold_out_g"]).all()          # 품절 22건 모두 찾고 오판 없음
    log = json.loads((tmp_path / "ingest_log.json").read_text(encoding="utf-8"))
    assert log["clean"]["closed_days"] == ["2026-01-01", "2026-02-17", "2026-09-25"]
    assert log["clean"]["discontinued"] == ["두바이쫀득쿠키"]


def test_run_with_pos_file(tmp_path):
    """run.py 실데이터 경로: --pos로 POS 원본부터 끝까지. 메뉴명 규칙이 없으면 통일 후보를 남긴다."""
    out = run_main(["--store", "sinchon-a", "--pos", str(SAMPLE / "pos_raw.csv"),
                    "--signals", str(SAMPLE / "signals.csv"), "--iterations", "30", "--artifacts", str(tmp_path)])
    for name in ["sales_clean.csv", "signals.csv", "store.json", "backtest.json", "forecast.json"]:
        assert (out / name).exists(), name
    cands = json.loads((out / "menu_merge_candidates.json").read_text(encoding="utf-8"))
    assert {"a": "아메리카노(ICE)", "b": "아이스 아메리카노", "score": 1.0} in cands


def test_unit_prices_from_amount_columns(tmp_path):
    """금액 열이 있으면 메뉴별 판매가(금액 합 ÷ 수량 합, 공급가액이면 부가세 포함)를 menu_prices.json에 남긴다."""
    import json
    from ml.ingest import ingest_store
    p = tmp_path / "items.csv"
    p.write_text("일자,품목명,수량,공급가액,부가세\n20261001,소금빵,10,30000,3000\n20261002,소금빵,10,30000,3000\n"
                 "20261001,아메리카노,4,16000,1600\n20261002,서비스 쿠키,2,0,0\n", encoding="utf-8")
    ingest_store(p, "s", tmp_path / "out")
    assert json.loads((tmp_path / "out" / "menu_prices.json").read_text(encoding="utf-8")) == {"소금빵": 3300, "아메리카노": 4400}

    q = tmp_path / "no_amount.csv"                                   # 금액 열이 없으면 파일을 만들지 않는다
    q.write_text("날짜,상품명,수량\n2026-10-01,소금빵,10\n", encoding="utf-8")
    ingest_store(q, "s", tmp_path / "out2")
    assert not (tmp_path / "out2" / "menu_prices.json").exists()
