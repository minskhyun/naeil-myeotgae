"""가상 POS 파일 만들기 (ingest.py 개발·테스트용).  ★ 열 이름·배치는 추정이다. 11/18 실제 파일을 보고 교체한다.

일부러 넣은 '실제 파일에서 흔한 골칫거리':
- 위에 제목·기간 줄이 있어 머리글이 1번째 줄이 아님
- 영수증 단위(한 줄 = 결제 한 건, 시각 포함) → 날짜·메뉴별 합산 필요
- 맨 아래 합계 행, 취소(음수 수량) 행
- 날짜가 20251101 같은 숫자, 수량이 "1"처럼 글자
- 한국 POS가 흔히 쓰는 cp949 인코딩 CSV

실행: python -m tests.fixtures.make_pos_fixtures   (프로젝트 최상위 폴더에서)
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data" / "sample" / "sinchon-a" / "pos_raw.csv"
OUT = Path(__file__).resolve().parent
DAYS = 10


def source() -> pd.DataFrame:
    """가상 매장의 처음 10일 (날짜·메뉴별 판매 수량) = 픽스처의 정답."""
    raw = pd.read_csv(SOURCE, parse_dates=["날짜"])
    return raw[raw["날짜"] < raw["날짜"].min() + pd.Timedelta(days=DAYS)].reset_index(drop=True)


def _with_title(table: pd.DataFrame, title_rows: list[list]) -> pd.DataFrame:
    """머리글 위에 제목 줄을 끼워 넣은 '머리글 없는' 표 (엑셀에 그대로 쓰기 위함)."""
    width = table.shape[1]
    top = [r + [None] * (width - len(r)) for r in title_rows]
    rows = top + [list(table.columns)] + table.astype(object).values.tolist()
    return pd.DataFrame(rows)


def make_toss(src: pd.DataFrame, rng) -> pd.DataFrame:
    """토스 스타일(추정): 영수증 단위, '결제일시'에 날짜+시각, 제목 2줄, 합계 행, 취소 행."""
    rows = []
    for r in src.itertuples():
        left = int(r.판매수량)
        while left > 0:                                         # 한 번에 1~2개씩 결제
            n = min(left, int(rng.integers(1, 3)))
            t = r.날짜 + pd.Timedelta(seconds=int(rng.integers(8 * 3600, 21 * 3600)))
            rows.append([t.strftime("%Y-%m-%d %H:%M:%S"), r.메뉴명, str(n), n * 3000])
            left -= n
    rows.sort(key=lambda x: x[0])
    first = rows[0]
    rows.insert(5, [first[0], first[1], "-1", -3000])            # 취소 (음수)
    rows.append(["합계", None, str(int(src["판매수량"].sum())), None])
    table = pd.DataFrame(rows, columns=["결제일시", "상품명", "수량", "결제금액"])
    return _with_title(table, [["상품별 판매 내역"], ["조회기간", "2025-11-01 ~ 2025-11-10"]]), first


def make_okpos(src: pd.DataFrame) -> pd.DataFrame:
    """OKPOS 스타일(추정): 일자별 상품 합계, 영업일자가 숫자(20251101), 상품코드 열, 빈 줄, 합계 행."""
    table = pd.DataFrame({
        "영업일자": src["날짜"].dt.strftime("%Y%m%d").astype(int),
        "상품코드": src["메뉴명"].astype("category").cat.codes.astype(int) + 1000,   # codes는 int8 → 1000을 못 담음
        "상품명": src["메뉴명"],
        "수량": src["판매수량"],
        "금액": src["판매금액"],
    }).astype(object)                                            # 숫자 열에 "합계" 글자를 넣으려면 object여야 함
    table.loc[len(table)] = ["합계", None, None, int(src["판매수량"].sum()), int(src["판매금액"].sum())]
    return _with_title(table, [["일자별 상품 매출"], []])


def main():
    rng = np.random.default_rng(7)
    src = source()
    toss, _ = make_toss(src, rng)
    toss.to_excel(OUT / "toss_receipts.xlsx", header=False, index=False)
    okpos = make_okpos(src)
    okpos.to_excel(OUT / "okpos_daily.xlsx", header=False, index=False)
    okpos.to_csv(OUT / "okpos_daily_cp949.csv", header=False, index=False, encoding="cp949")
    src.to_csv(OUT / "expected_daily.csv", index=False, encoding="utf-8")   # 정답
    print("저장:", OUT)


if __name__ == "__main__":
    main()
