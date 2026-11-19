"""POS 파일 → 정리된 판매 기록(SalesRow 형식)  (TASKS.md §2·§3)

    read_pos()              엑셀/CSV에서 머리글 줄과 열을 찾아 (date, menu_raw, qty)로 읽는다
    suggest_menu_merges()   이름이 비슷한 메뉴 '후보'만 뽑는다 (자동으로 합치지 않음)
    clean_sales()           승인된 메뉴명 규칙 적용 → 날짜×메뉴 합산 → 0개 판매 채우기 → 휴무 제외 → 품절 표시
    ingest_store()          위를 한 번에 → data/artifacts/{store_id}/sales_clean.csv

★ 11/18 실제 파일이 오면 COLUMN_MAP의 열 이름 후보만 고친다. 다른 코드는 고치지 않는 것이 목표.
"""
import difflib
import json
import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

from contracts.schemas import SalesRow

# ---------------------------------------------------------------- 11/18에 고칠 곳
# 열 이름 후보 (공백은 무시하고 비교). 실제 파일의 머리글을 보고 여기에 추가한다.
COLUMN_MAP = {
    "toss":  {"date": ["날짜", "판매일자", "일자", "판매일시", "결제일시"], "menu": ["상품명", "메뉴명"],
              "qty": ["수량", "판매수량"], "time": ["시간", "판매시각", "결제시각"]},
    "okpos": {"date": ["일자", "영업일자", "판매일자"], "menu": ["상품명"],
              "qty": ["수량", "판매수량"], "time": ["시간", "판매시간"]},
    # 상품별 매출 엑셀 (일자 · 품목코드 · 품목명 · 규격 · 수량 · 공급가액 · 부가세). 달마다 시트가 나뉘어 있다
    "items": {"date": ["일자", "판매일자"], "menu": ["품목명"], "qty": ["수량", "판매수량"]},
}
# 금액 열 (있으면 메뉴별 판매가 = 금액 합 ÷ 수량 합 → menu_prices.json. 예측에는 쓰지 않고 '얼마를 아꼈나' 환산에만 쓴다)
AMOUNT_COLUMNS = {"amount": ["공급가액", "판매금액", "매출액", "실매출액", "결제금액", "금액"], "vat": ["부가세"]}
HEADER_SEARCH_ROWS = 10                          # 머리글을 찾을 범위 (위에서 10줄)
TOTAL_WORDS = ("합계", "소계", "총계", "총합")    # 이런 글자가 메뉴·날짜 칸에 있으면 합계 행
# 메뉴가 아닌 품목: 이름이 금액뿐인 것('10000원' = 금액권·임의 금액 결제), 충전. 준비할 것이 아니므로 예측에서 뺀다
NON_MENU = re.compile(r"^\d[\d,]*\s*원$|충전")
SOLD_OUT_MIN_REPEATS = 3                         # 같은 최댓값에서 3번 이상 멈추면 품절로 본다 (TASKS §3)
SOLD_OUT_MIN_QTY = 10                            # 단, 최댓값이 10개 이상일 때만 (적게 팔리는 메뉴의 우연한 반복 제외)
SOLD_OUT_PILE_RATIO = 3.0                        # 그리고 최댓값 횟수가 바로 아래 세 값 평균 횟수의 3배 이상일 때만
                                                 # (가상 데이터를 보고 정한 값 → 11/18 실데이터에서 근거를 눈으로 확인)
DISCONTINUED_DAYS = 14                           # 최근 14일 판매가 없으면 단종으로 본다
MERGE_THRESHOLD = 0.75                           # 메뉴명 유사도가 이 이상이면 통일 후보로 보여 준다


# ---------------------------------------------------------------- 1) 읽기

def _norm_header(x) -> str:
    return re.sub(r"\s+", "", str(x)) if pd.notna(x) else ""


def _read_raw(path: Path) -> list[pd.DataFrame]:
    """머리글 없이 통째로 읽는다 (머리글이 몇 번째 줄인지는 아직 모르므로). 엑셀은 시트마다 표 하나, CSV는 표 하나."""
    if path.suffix.lower() in (".xlsx", ".xlsm", ".xls"):
        return list(pd.read_excel(path, sheet_name=None, header=None, dtype=object).values())
    for enc in ("utf-8-sig", "cp949"):           # 한국 POS의 CSV는 cp949(EUC-KR)인 경우가 많다
        try:
            return [pd.read_csv(path, header=None, dtype=object, encoding=enc)]
        except UnicodeDecodeError:
            continue
    raise ValueError(f"{path.name}: 글자 인코딩을 알 수 없습니다 (utf-8, cp949 모두 실패).")


def _find_header(raw: pd.DataFrame, pos_type: str):
    """위 10줄에서 date·menu·qty 열 이름이 모두 있는 줄을 찾는다 → (포스 종류, 줄 번호, {역할: 열 번호})."""
    types = list(COLUMN_MAP) if pos_type == "auto" else [pos_type]
    for row in range(min(HEADER_SEARCH_ROWS, len(raw))):
        cells = [_norm_header(x) for x in raw.iloc[row]]
        for t in types:
            cols = {}
            for role, names in COLUMN_MAP[t].items():
                hit = [i for i, c in enumerate(cells) if c in names]
                if hit:
                    cols[role] = hit[0]
            if {"date", "menu", "qty"} <= cols.keys():
                return t, row, cols
    preview = "\n".join(" | ".join(_norm_header(x) for x in raw.iloc[r]) for r in range(min(5, len(raw))))
    raise ValueError(f"머리글(날짜·메뉴·수량 열)을 찾지 못했습니다. ml/ingest.py의 COLUMN_MAP에 열 이름을 추가하세요.\n"
                     f"파일 첫 줄들:\n{preview}")


def _parse_dates(s: pd.Series) -> pd.Series:
    """여러 날짜 표기를 처리: 엑셀 날짜, '2026-10-01', '2026.10.01', '2026/10/01', '20261001', 시각 포함."""
    if pd.api.types.is_datetime64_any_dtype(s):
        return s
    text = s.astype(str).str.strip().str.replace(r"\.0$", "", regex=True)          # 20261001.0 → 20261001
    ymd = text.str.fullmatch(r"\d{8}")
    out = pd.to_datetime(text.where(~ymd), errors="coerce", format="mixed")
    out[ymd] = pd.to_datetime(text[ymd], format="%Y%m%d", errors="coerce")
    return out


def _parse_qty(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.replace(",", "").str.strip(), errors="coerce")   # "1,234" → 1234


def read_pos(path, pos_type: str = "auto") -> tuple[pd.DataFrame, dict]:
    """POS 파일 → (표[date, menu_raw, qty(, time)], 기록).  영수증 단위면 날짜·메뉴별로 합산한다.

    ※ TASKS.md는 표만 돌려준다고 했지만, 뺀 행 수를 남기려고 기록(dict)도 함께 돌려준다.
    """
    path = Path(path)
    sheets = _read_raw(path)
    found_type, header_row, cols = _find_header(sheets[0], pos_type)
    # 달마다 시트를 나눈 파일('9월', '10월'): 첫 시트와 머리글이 같은 시트를 아래로 이어 붙인다 (다른 모양의 시트는 읽지 않음)
    header = [_norm_header(x) for x in sheets[0].iloc[header_row]]
    same = [s for s in sheets if len(s) > header_row and [_norm_header(x) for x in s.iloc[header_row]] == header]
    body = pd.concat([s.iloc[header_row + 1:] for s in same], ignore_index=True)

    df = pd.DataFrame({
        "date": _parse_dates(body.iloc[:, cols["date"]]),
        "menu_raw": body.iloc[:, cols["menu"]].astype("string").str.strip(),
        "qty": _parse_qty(body.iloc[:, cols["qty"]]),
    })
    money = {}
    for role, names in AMOUNT_COLUMNS.items():                      # 금액 열 (공급가액이면 부가세를 더해 판매가로)
        hit = [header.index(n) for n in names if n in header]
        if hit:
            money[role] = hit[0]
    if "amount" in money:
        df["amount"] = _parse_qty(body.iloc[:, money["amount"]])          # 금액이 빈 줄은 빈 값 그대로 (판매가 계산에서 뺀다)
        if "vat" in money and header[money["amount"]] == "공급가액":
            df["amount"] += _parse_qty(body.iloc[:, money["vat"]]).fillna(0)
    # 판매 시각: 따로 열이 있거나, 날짜 칸에 시각이 같이 들어 있는 경우 (영수증 단위 파일)
    if "time" in cols:
        df["time"] = body.iloc[:, cols["time"]].astype("string").str.strip().to_numpy()
    elif (df["date"].dropna().dt.normalize() != df["date"].dropna()).any():
        df["time"] = df["date"].dt.strftime("%H:%M:%S")
    df["date"] = df["date"].dt.normalize()

    is_total = (df["menu_raw"].fillna("").str.contains("|".join(TOTAL_WORDS))
                | body.iloc[:, cols["date"]].astype(str).str.contains("|".join(TOTAL_WORDS)).to_numpy())
    is_blank = df["date"].isna() | df["menu_raw"].isna() | df["qty"].isna()
    is_cancel = df["qty"] < 0
    is_other = df["menu_raw"].fillna("").str.contains(NON_MENU) & ~is_total & ~is_blank
    log = dict(file=path.name, pos_type=found_type, header_row=int(header_row), sheets=len(same), rows_read=len(df),
               dropped_total_or_blank=int((is_total | is_blank).sum()),
               dropped_cancel=int((is_cancel & ~is_total & ~is_blank).sum()),
               dropped_non_menu=int(is_other.sum()), non_menu=sorted(df.loc[is_other, "menu_raw"].unique()))
    df = df[~(is_total | is_blank | is_cancel | is_other)]
    if "amount" in df:                                              # 메뉴별 판매가 = 금액 합 ÷ 수량 합 (금액을 아는 줄만)
        sums = df[df["amount"].notna()].groupby("menu_raw")[["amount", "qty"]].sum()
        sums = sums[(sums["qty"] > 0) & (sums["amount"] > 0)]
        log["prices"] = {m: round(float(a / q)) for m, a, q in sums.itertuples()}

    log["receipt_level"] = bool(df.duplicated(["date", "menu_raw"]).any())   # 같은 날·메뉴가 여러 줄 = 영수증 단위
    keys = ["date", "menu_raw"]
    summed = df.groupby(keys, as_index=False)["qty"].sum()
    if "time" in df:                                                # 메뉴별 그날 첫·마지막 판매 시각
        times = df.groupby(keys)["time"].agg(first_time="min", last_time="max").reset_index()
        summed = summed.merge(times, on=keys, how="left")
    df = summed
    log["rows_out"] = len(df)
    return df.reset_index(drop=True), log


# ---------------------------------------------------------------- 2) 메뉴명 통일 후보

_TEMP_TAGS = [("ICE", r"\(?\b(ice|iced)\b\)?|아이스"), ("HOT", r"\(?\bhot\b\)?|따뜻한|핫")]


def _menu_key(name: str) -> tuple[str | None, str]:
    """'아메리카노(ICE)' → ('ICE', '아메리카노'),  '아이스 아메리카노' → ('ICE', '아메리카노')."""
    s, tag = str(name).lower(), None
    for t, pattern in _TEMP_TAGS:
        if re.search(pattern, s):
            tag, s = t, re.sub(pattern, "", s)
    s = re.sub(r"[\s()\[\]{}\-_/·.,]", "", s)      # 공백·괄호·기호 제거
    return tag, s


def temp_tag(name: str) -> str:
    """메뉴 이름의 온도 표기: 'ICE' / 'HOT' / '-'(표기 없음: 빵·디저트, 또는 표기 안 한 음료)."""
    return _menu_key(name)[0] or "-"


def suggest_menu_merges(menus, threshold: float = MERGE_THRESHOLD) -> list[tuple[str, str, float]]:
    """이름이 비슷한 메뉴 쌍 → [(a, b, 유사도)] (유사도 높은 순).  ★ 후보일 뿐, 합치는 건 사람이 승인한 뒤.

    아이스/핫 표기는 따로 떼어 비교한다: ICE와 HOT은 다른 메뉴이므로 후보로 내지 않고,
    한쪽에만 표기가 있으면 점수를 조금 깎는다 ('아메리카노'가 원래 따뜻한 것일 수도 있으므로).
    이름 속 숫자가 다르면 크기·개수·가격이 다른 메뉴로 보고 후보로 내지 않는다 ('케이크 4인'↔'6인', '2개입'↔'4개입').
    (11/15 프랑스 베이커리 실데이터: 후보 51쌍 중 27쌍이 'TARTE 4P'↔'6P' 같은 크기 차이였다)
    """
    menus = sorted(set(menus))
    keys = {m: _menu_key(m) for m in menus}
    out = []
    for i, a in enumerate(menus):
        for b in menus[i + 1:]:
            (ta, ka), (tb, kb) = keys[a], keys[b]
            if (ta and tb and ta != tb) or re.findall(r"\d+", a) != re.findall(r"\d+", b):
                continue
            # 한글을 자모로 풀어 비교: '크로와상' vs '크루아상'은 글자 단위로는 0.5지만 자모로는 0.78
            score = difflib.SequenceMatcher(None, unicodedata.normalize("NFD", ka),
                                            unicodedata.normalize("NFD", kb)).ratio()
            if (ta is None) != (tb is None):
                score *= 0.9
            if score >= threshold:
                out.append((a, b, round(score, 3)))
    return sorted(out, key=lambda x: -x[2])


# ---------------------------------------------------------------- 3) 정리

def sold_out_evidence(qty: pd.Series) -> dict:
    """메뉴 하나의 판매량들 → 품절 판단 근거.  수요가 '굽는 개수'에 막히면 판매량이 그 값에 쌓인다:
         소금빵  80개 13번, 79개 2번, 78개 1번   → 80에서 막힘 (품절)
         식빵    21개  4번, 20개 2번, 19개 3번   → 자연스럽게 줄어드는 꼬리 (품절 아님)
    """
    counts = qty.value_counts()
    top = int(qty.max())
    n_top = int(counts[top])
    near = [int(counts.get(top - k, 0)) for k in (1, 2, 3)]          # 최댓값 바로 아래 세 값의 횟수
    pile = n_top / max(float(np.mean(near)), 1.0)                     # 최댓값에 얼마나 몰렸나
    is_sold_out = n_top >= SOLD_OUT_MIN_REPEATS and top >= SOLD_OUT_MIN_QTY and pile >= SOLD_OUT_PILE_RATIO
    return dict(qty=top, days=n_top, below=near, pile=round(pile, 2), sold_out=bool(is_sold_out))


def mark_sold_out(sales: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """메뉴별로 판매량이 최댓값에 쌓여 있으면 그 값과 같은 날들을 품절(sold_out=True)로 표시한다.
    추정이므로 메뉴마다 근거(sold_out_evidence)를 함께 돌려준다 → ingest_log.json에서 사람이 확인."""
    evidence = {m: sold_out_evidence(g) for m, g in sales.groupby("menu")["qty"]}
    flagged = {m: e["qty"] for m, e in evidence.items() if e["sold_out"]}
    sales = sales.assign(sold_out=sales["qty"] == sales["menu"].map(flagged))   # 표시 안 된 메뉴는 NaN과 비교 → False
    return sales, evidence


def clean_sales(pos: pd.DataFrame, store_id: str, menu_map: dict[str, str] | None = None) -> tuple[pd.DataFrame, dict]:
    """read_pos 결과 → SalesRow 형식 표 + 기록."""
    menu_map = menu_map or {}
    df = pos.assign(menu=pos["menu_raw"].map(lambda m: menu_map.get(m, m)).str.replace(r"\s+", " ", regex=True))
    df = df.groupby(["date", "menu"], as_index=False)["qty"].sum()     # 통일된 이름끼리 합산

    # POS는 0개 판매를 기록하지 않는다 → 영업일 × (메뉴의 첫 판매 ~ 마지막 판매 기간)을 0으로 채운다
    wide = df.pivot_table(index="date", columns="menu", values="qty", aggfunc="sum")
    all_days = pd.date_range(wide.index.min(), wide.index.max(), freq="D")
    wide = wide.reindex(all_days)
    total = wide.sum(axis=1, min_count=1)
    closed = wide.index[total.isna() | (total == 0)]                    # 전 메뉴 판매 0 = 휴무 → 행을 뺀다
    wide = wide.drop(closed)
    first, last = wide.notna().idxmax(), wide[::-1].notna().idxmax()
    rows = []
    for menu in wide.columns:
        s = wide.loc[first[menu]:last[menu], menu].fillna(0)
        rows.append(pd.DataFrame({"date": s.index, "menu": menu, "qty": s.to_numpy().astype(int)}))
    sales = pd.concat(rows, ignore_index=True)
    sales.insert(1, "store_id", store_id)
    sales, evidence = mark_sold_out(sales)
    sales = sales.sort_values(["date", "menu"]).reset_index(drop=True)

    end = sales["date"].max()
    discontinued = sorted(m for m, d in last.items() if (end - d).days >= DISCONTINUED_DAYS)
    log = dict(
        days=int(sales["date"].nunique()), first=str(sales["date"].min().date()), last=str(end.date()),
        menus=int(sales["menu"].nunique()), closed_days=[str(d.date()) for d in closed],
        menu_map_applied={k: v for k, v in menu_map.items() if k in set(pos["menu_raw"])},
        sold_out={m: e for m, e in evidence.items() if e["sold_out"]},
        sold_out_evidence=evidence,                                     # 모든 메뉴의 근거 (사람이 확인용)
        discontinued=discontinued,
    )
    return sales, log


# ---------------------------------------------------------------- 4) 한 번에

def ingest_store(pos_path, store_id: str, out: Path, pos_type: str = "auto") -> str:
    """POS 파일 → out/sales_clean.csv (+ ingest_log.json, menu_merge_candidates.json).  run.py가 부른다.

    메뉴명 규칙은 out/menu_map.json에 사람이 승인한 것만 적용한다. 없으면 그대로 둔다.
    """
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    pos, read_log = read_pos(pos_path, pos_type)
    map_path = out / "menu_map.json"
    menu_map = json.loads(map_path.read_text(encoding="utf-8")) if map_path.exists() else {}
    sales, clean_log = clean_sales(pos, store_id, menu_map)

    for rec in sales.to_dict("records"):                                # 계약 형식 검사
        SalesRow.model_validate(rec)
    sales.assign(date=sales["date"].dt.strftime("%Y-%m-%d")).to_csv(out / "sales_clean.csv", index=False,
                                                                     encoding="utf-8")
    if "last_time" in pos:                                              # 판매 시각 (품절 시각 추정용, P1)
        pos.to_csv(out / "sale_times.csv", index=False, encoding="utf-8")

    candidates = suggest_menu_merges(sales["menu"].unique())
    (out / "menu_merge_candidates.json").write_text(json.dumps(
        [dict(a=a, b=b, score=s) for a, b, s in candidates], ensure_ascii=False, indent=1), encoding="utf-8")
    prices = {menu_map.get(m, m): p for m, p in read_log.pop("prices", {}).items()}      # 판매가 (금액 열이 있을 때)
    if prices:
        (out / "menu_prices.json").write_text(json.dumps(prices, ensure_ascii=False, indent=1), encoding="utf-8")
    log = dict(read=read_log, clean=clean_log, merge_candidates=len(candidates), menus_with_price=len(prices))
    (out / "ingest_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")

    parts = [f"{read_log['pos_type']} 형식, {clean_log['days']}일·메뉴 {clean_log['menus']}개",
             f"합계·빈 행 {read_log['dropped_total_or_blank']}개, 취소 {read_log['dropped_cancel']}개 제외"
             + (f", 메뉴가 아닌 품목(금액권·충전) {len(read_log['non_menu'])}개 제외" if read_log["non_menu"] else "")
             + (f", 시트 {read_log['sheets']}개를 이어 읽음" if read_log["sheets"] > 1 else "")]
    if clean_log["closed_days"]:
        parts.append(f"휴무 {len(clean_log['closed_days'])}일")
    if clean_log["sold_out"]:
        parts.append(f"품절 추정 {sum(v['days'] for v in clean_log['sold_out'].values())}건")
    if candidates:
        parts.append(f"메뉴명 통일 후보 {len(candidates)}쌍 → menu_merge_candidates.json 확인 후 menu_map.json에 승인")
    return ", ".join(parts)
