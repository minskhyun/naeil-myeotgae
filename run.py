"""한 매장 전체 실행: ingest → evaluate → predict.  웹(backend/app/main.py)도 이 파일을 그대로 실행한다.

    python run.py --store sinchon-a --demo                          # 가상 데이터로 끝까지
    python run.py --store sinchon-a --demo --demo-days 35           # 가상 데이터를 35일로 잘라 '짧은 데이터 모드' 시연
    python run.py --store seongsu-a --pos data/raw/seongsu-a.xlsx \\
                  --address "서울 성동구 서울숲2길 12-7"            # 실데이터: 주소로 주변 정보를 자동 수집
    python run.py --store seongsu-a --from-step predict             # 앞 단계 결과 파일을 그대로 쓰고 predict만

단계마다 하는 일 (함수 이름 = step_단계)
    ingest     POS 파일 → sales_clean.csv,  매장 설정 → store.json,  주변 정보 → signals.csv·collection.json
               + 무엇을 왜 모았는지 요약 → sources_report.json
    evaluate   과거 기록으로 검증: 모델 비교, 쓸 신호 고르기 → backtest.json
    predict    내일 예측·근거·준비량 + AI 주의 안내 → forecast.json

결과는 모두 data/artifacts/{store_id}/ 에 쌓인다 (.gitignore 대상, 커밋되지 않음).
    store.json         매장 설정 (contracts.StoreConfig. 직접 열어 고쳐도 됨)
    sales_clean.csv    정리된 판매 기록
    collectors/        공공 데이터 수집기 결과 (날씨·학사일정·행사 원본, 주변 시설, 정보원 계획)
    signals.csv        외부 신호 (있으면)
    collection.json    AI 주의 안내에 쓸 행사·뉴스 원문 (있으면)
    sources_report.json  주변 정보 수집 요약 (화면의 '주변 정보' 탭)
    backtest.json      검증 결과
    forecast.json      내일 예측
    llm_cache/         AI 주의 안내 응답 저장 (같은 입력은 다시 부르지 않음)
"""
import argparse
import json
import shutil
import sys
import time
from pathlib import Path

import pandas as pd

from agent import collect, collectors_bridge, geocode
from agent.collectors_bridge import OBSERVED_PROXY
from agent.report import write_report
from contracts.schemas import BacktestResult, CollectionItem, SignalRow, StoreConfig
from ml import progress
from ml.alerts import make_warnings
from ml.evaluate import run_backtest, write_backtest
from ml.features import load_sales, load_signals, to_kst
from ml.ingest import ingest_store
from ml.paths import ARTIFACTS, RAW, SAMPLE
from ml.predict import predict_from_backtest, write_forecast

STEPS = ["ingest", "evaluate", "predict"]
PROGRESS_FILE = "progress.json"        # 실행 중에 알린 것 전부 (ml/progress.py) → 웹의 '분석 과정 다시 보기'


def _need(path: Path, step: str) -> Path:
    """다음 단계에 필요한 파일이 없으면, 무엇을 먼저 실행해야 하는지 알려 주고 멈춘다."""
    if not path.exists():
        raise SystemExit(f"{path.name}이(가) 없습니다: {path}\n→ '{step}' 단계부터 실행하세요 (--from-step {step}).")
    return path


def _load(out: Path) -> tuple[StoreConfig, pd.DataFrame, pd.DataFrame | None]:
    """앞 단계가 남긴 파일 읽기: (매장 설정, 판매 기록, 신호 또는 None)."""
    sales = load_sales(_need(out / "sales_clean.csv", "ingest"))
    store = StoreConfig.read(_need(out / "store.json", "ingest"))
    signals = load_signals(out / "signals.csv") if (out / "signals.csv").exists() else None
    return store, sales, signals


# ---------------------------------------------------------------- 1. ingest

def step_ingest(args, out: Path) -> str:
    out.mkdir(parents=True, exist_ok=True)
    if args.demo:
        return _ingest_demo(args, out)
    if not args.pos:
        raise SystemExit("--demo 또는 --pos <POS 파일> 중 하나가 필요합니다.")
    return _ingest_pos(args, out)


def _ingest_demo(args, out: Path) -> str:
    """가상 매장: data/sample/{store}의 파일을 그대로 가져온다 (주변 정보도 미리 만들어 둔 것)."""
    src = SAMPLE / args.store
    if not (src / "sales.csv").exists():
        raise SystemExit(f"가상 데이터가 없습니다: {src}  (python -m ml.sample_data 로 만드세요)")
    sales = load_sales(src / "sales.csv")
    if args.demo_days:                                    # 앞 N일만 남겨 짧은 데이터 상황을 흉내 낸다
        sales = sales[sales["date"] < sales["date"].min() + pd.Timedelta(days=args.demo_days)]
    sales.assign(date=sales["date"].dt.strftime("%Y-%m-%d")).to_csv(out / "sales_clean.csv", index=False, encoding="utf-8")
    shutil.copyfile(src / "signals.csv", out / "signals.csv")
    shutil.copyfile(src / "store.json", out / "store.json")
    if (src / "collectors").exists():                     # 정보원 선택 에이전트를 미리 돌려 둔 결과 (sample_data.py 참고)
        shutil.copytree(src / "collectors", out / "collectors", dirs_exist_ok=True)
    _tell_sales(sales)
    _tell_demo_surroundings(args.store, out)
    note = f"가상 데이터 {sales['date'].nunique()}일, {len(sales)}행"
    if args.collection:
        note += ", " + _import_collection(Path(args.collection), out, append=False)
        seen = set()                                      # 화면에 알리기: 가상 기사 제목 (같은 글은 한 번)
        for item in json.loads((out / "collection.json").read_text(encoding="utf-8")):
            if item["title"] not in seen:
                seen.add(item["title"])
                progress.emit("article", title=item["title"], url=item["source_url"])
    write_report(args.store, out, ["가상 매장입니다. 판매 기록·날씨·학사일정·근처 행사와 기사는 모두 가상으로 만든 것입니다."])
    return note


def _tell_sales(sales: pd.DataFrame) -> None:
    """화면에 알리기: 판매 기록이 며칠치, 메뉴 몇 개인지."""
    progress.emit("sales", days=int(sales["date"].nunique()), menus=int(sales["menu"].nunique()),
                  first=sales["date"].min().date(), last=sales["date"].max().date())


def _tell_demo_surroundings(store_id: str, out: Path) -> None:
    """가상 매장: 미리 만들어 둔 주변 시설·정보원 계획과 가상 기사를 화면에 알린다 (실제 수집은 하지 않는다)."""
    work_dir = out / "collectors"
    nearby = work_dir / f"{store_id}_nearby.json"
    if nearby.exists():
        at = json.loads(nearby.read_text(encoding="utf-8"))
        store = StoreConfig.read(out / "store.json")
        progress.emit("store", name=store.name or store_id, address=store.address, lat=at.get("lat"), lon=at.get("lon"))
        progress.emit("step", step="collect", status="start")
        collectors_bridge.tell_plan(store_id, work_dir)
    signals = load_signals(out / "signals.csv")
    collectors_bridge.tell_coverage({name: set(pd.to_datetime(g).dt.date) for name, g in signals.groupby("signal")["date"]})
    progress.emit("step", step="collect", status="done")


def _ingest_pos(args, out: Path) -> str:
    """실데이터: POS 파일 정리 → 매장 설정 → 주변 정보 (사장님은 POS와 주소만 준다)."""
    progress.status("판매 기록을 읽는 중")
    notes = [ingest_store(Path(args.pos), args.store, out, pos_type=args.pos_type)]
    _tell_sales(load_sales(out / "sales_clean.csv"))
    if args.address:
        progress.status("매장 위치를 찾는 중")
    store, where = _store_setup(args, out)
    progress.emit("store", name=store.name or store.store_id, address=store.address, lat=store.lat, lon=store.lon)
    notes.append(where)
    collected = []                                         # 정보원별 수집 메모 (sources_report.json에 남긴다)
    if args.signals:                                       # 신호 파일을 직접 주면 자동 수집을 하지 않는다
        notes.append(_write_signals(load_signals(args.signals), args.store, out, Path(args.signals).name))
        collected.append(f"신호 파일을 직접 받음: {Path(args.signals).name}")
    else:
        progress.emit("step", step="collect", status="start")
        summary, collected = _auto_collect(store, out)
        progress.emit("step", step="collect", status="done")
        notes.append(summary)
    if args.collection:                                    # 직접 준 원문은 자동 수집분 뒤에 덧붙인다
        notes.append(_import_collection(Path(args.collection), out, append=True))
    write_report(args.store, out, collected)
    return ", ".join(n for n in notes if n)


def _store_setup(args, out: Path) -> tuple[StoreConfig, str]:
    """store.json을 만들거나 고친다 (영업 종료 시각, 주소 → 위도·경도). 돌려주는 값: (설정, 위치 메모)."""
    path = out / "store.json"
    store = StoreConfig.read(path) if path.exists() else \
        StoreConfig(store_id=args.store, **({"close_time": args.close_time} if args.close_time else {}))
    note = ""
    if args.address and args.address != store.address:
        try:
            lat, lon, found = geocode.geocode(args.address)
            store.address, store.lat, store.lon = args.address, round(lat, 5), round(lon, 5)
            note = f"위치 {found.split(',')[0]} ({lat:.4f}, {lon:.4f})"
        except Exception as e:                                  # 위치를 못 찾아도 예측은 계속 (주변 정보 없이)
            note = f"주소로 위치를 찾지 못함({type(e).__name__}) → 주변 정보 없이 진행"
    store.write(path)
    return store, note


def _auto_collect(store: StoreConfig, out: Path) -> tuple[str, list[str]]:
    """매장 위치로 주변 정보를 모아 signals.csv(+원문은 collection.json)로. 정보원마다 실패해도 예측은 계속.
    무엇을 모으는지는 agent/collect.py의 SOURCES 참고. 키는 맨 위 .env 하나 (README '키 준비').
    돌려주는 값: (실행 기록에 찍을 한 줄, 정보원별 메모)"""
    if store.lat is None or store.lon is None:
        note = "주변 정보 없음 (매장 위치를 모름: 주소를 넣으면 날씨·행사를 자동으로 붙임)"
        return note, [note]
    sales = load_sales(out / "sales_clean.csv")
    dates = sales["date"]
    start = dates.min() - pd.Timedelta(days=35)                 # 기온 '최근 28일 평균'용 여유
    end = max(dates.max(), pd.Timestamp.today().normalize()) + pd.Timedelta(days=7)
    target = (dates.max() + pd.Timedelta(days=1)).date()        # 내일 = 예측 날짜 (메뉴 검색량 안내를 붙일 날)
    menus = sales.groupby("menu")["qty"].sum().sort_values(ascending=False).index.tolist()   # 판매량 많은 순
    rows, items, notes = collect.collect_all(store, start.date(), end.date(), work_dir=out / "collectors",
                                             sources_path=RAW / f"{store.store_id}_event_sources.txt",
                                             target=target, menus=menus)
    if items:
        _save_collection([i.model_dump(mode="json") for i in items], out, append=False)
        notes.append(f"행사 원문 {len(items)}개")
    if not rows:
        return "주변 정보 없음 (" + "; ".join(notes) + ")", notes
    signals = pd.DataFrame([r.model_dump() for r in rows])
    summary = "주변 정보 자동 수집 " + _write_signals(signals, store.store_id, out, "자동 수집") + " [" + "; ".join(notes) + "]"
    return summary, notes


def _write_signals(signals: pd.DataFrame, store_id: str, out: Path, source: str) -> str:
    """신호 표 → 계약(SignalRow) 검사 → 이 매장 것만 out/signals.csv로 저장."""
    for rec in signals.to_dict("records"):                      # 한 줄이라도 형식이 틀리면 여기서 멈춘다
        SignalRow.model_validate(rec)
    mine = signals[signals["store_id"] == store_id]
    if mine.empty:
        raise SystemExit(f"{source}에 store_id='{store_id}'인 신호가 없습니다 (있는 매장: {sorted(set(signals['store_id']))}).")
    mine.to_csv(out / "signals.csv", index=False, encoding="utf-8")
    note = f"신호 {len(mine)}행 ({', '.join(sorted(set(mine['signal'])))})"
    proxy = int(mine["source_url"].str.contains(OBSERVED_PROXY, regex=False).sum())
    if proxy:                                                   # 실제 예보가 아닌 줄 → 결과를 말할 때 밝혀야 함
        note += f" ※ 관측값을 예보 대신 쓴 줄 {proxy}행: 검증 성능이 실제보다 조금 좋게 나올 수 있음"
    return note


def _save_collection(items: list[dict], out: Path, append: bool) -> None:
    """원문을 out/collection.json에 저장. append면 이미 있는 것(자동 수집분)에 덧붙인다."""
    path = out / "collection.json"
    old = json.loads(path.read_text(encoding="utf-8")) if append and path.exists() else []
    path.write_text(json.dumps(old + items, ensure_ascii=False, indent=1), encoding="utf-8")


def _import_collection(path: Path, out: Path, append: bool = False) -> str:
    """원문 모음(.json, CollectionItem 목록) → 형식 검사 → 공개 시각을 한국 시간으로 → out/collection.json."""
    items = []
    for i, rec in enumerate(json.loads(path.read_text(encoding="utf-8-sig"))):
        try:
            item = CollectionItem.model_validate(rec)
        except ValueError as e:
            raise SystemExit(f"{path.name}의 {i}번째 항목 형식이 틀립니다:\n{e}")
        if item.published_at is not None:
            item.published_at = to_kst(item.published_at).to_pydatetime()
        items.append(item.model_dump(mode="json"))
    _save_collection(items, out, append)
    return f"원문 {len(items)}개"


# ---------------------------------------------------------------- 2. evaluate

def step_evaluate(args, out: Path) -> str:
    store, sales, signals = _load(out)
    progress.status("지난 기록으로 예측을 시험해, 어떤 정보가 실제로 도움이 되는지 확인하는 중")
    price_file = out / "menu_prices.json"                     # 판매가 (POS 파일에 금액 열이 있었을 때만 있다)
    prices = json.loads(price_file.read_text(encoding="utf-8")) if price_file.exists() else None
    bt = run_backtest(sales, signals, close_time=store.close_time, prices=prices, **args.model_kwargs)
    write_backtest(bt, out.parent)
    for d in bt.decisions:                                    # 화면: 정보 묶음마다 쓸지 말지
        progress.emit("decision", group=d.signal_group, adopted=d.adopted, reason=d.reason)
    test = {s.model[:2]: s for s in bt.test_scores}           # "M3(채택 신호만)" → "M3"
    mine, base = test.get(bt.chosen_model[:2]), test.get("M0")
    if mine and base:
        days = (pd.Timestamp(bt.test_period[1]) - pd.Timestamp(bt.test_period[0])).days + 1 if bt.test_period else None
        per_day = lambda s: round((s.over + s.under) / max(s.days, 1), 1)                 # noqa: E731  하루에 남거나 모자란 개수
        saved = round((base.amount - mine.amount) / max(mine.days, 1)) if mine.amount is not None and base.amount is not None else None
        progress.emit("scores", model=bt.chosen_model, wape=round(mine.wape, 4), base_wape=round(base.wape, 4),
                      coverage=round(mine.coverage_80, 4), test_days=days, miss=per_day(mine), base_miss=per_day(base),
                      saved_amount=saved)
    adopted = [d.signal_group for d in bt.decisions if d.adopted] or ["없음"]
    return f"선택 모델 {bt.chosen_model}, 채택 신호 {', '.join(adopted)}"


# ---------------------------------------------------------------- 3. predict

def step_predict(args, out: Path) -> str:
    store, sales, signals = _load(out)
    progress.status("내일 메뉴별 판매량을 예측하는 중")
    bt = BacktestResult.model_validate_json(_need(out / "backtest.json", "evaluate").read_text(encoding="utf-8"))
    fc = predict_from_backtest(sales, signals, bt, close_time=store.close_time, prep_mode=store.prep_mode,
                               menus=store.menus, **args.model_kwargs)
    note = ""
    if store.menus is not None:                               # 오타·아직 안 판 신메뉴는 예측할 수 없으니 알려 준다
        missing = sorted(set(store.menus) - {r.menu for r in fc.rows})
        if missing:
            note += f", menus 중 예측 못 한 메뉴(최근 14일 판매 기록 없음·오타?): {', '.join(missing)}"
    if (out / "collection.json").exists():                    # 모은 원문이 있으면 AI 주의 안내 (숫자는 안 바꿈)
        try:
            progress.status("AI가 모은 소식 중 주의할 것이 있는지 읽는 중")
            collection = json.loads((out / "collection.json").read_text(encoding="utf-8"))
            fc.warnings = make_warnings(fc, collection, out / "llm_cache", close_time=store.close_time)
            note += f", 경고 {len(fc.warnings)}개"
        except Exception as e:                                # 안내는 부가 기능: 실패해도 예측은 저장
            note += f", 경고 생성 실패({type(e).__name__}) → 경고 없이 저장"
    write_forecast(fc, out.parent)
    top = sorted(fc.rows, key=lambda r: r.pred, reverse=True)[:5]
    progress.emit("forecast", date=fc.rows[0].date, menus=len(fc.rows), warnings=[w.message for w in fc.warnings],
                  top=[dict(menu=r.menu, prep=r.prep_qty, pred=round(r.pred)) for r in top])
    return f"{fc.rows[0].date} 메뉴 {len(fc.rows)}개 예측{note}"


STEP_FUNCS = {"ingest": step_ingest, "evaluate": step_evaluate, "predict": step_predict}


# ---------------------------------------------------------------- 실행

def parse_args(argv=None):
    p = argparse.ArgumentParser(description="내일몇개 예측 엔진: 한 매장 전체 실행")
    p.add_argument("--store", required=True, help="매장 ID (예: sinchon-a)")
    p.add_argument("--demo", action="store_true", help="data/sample/{store}의 가상 데이터로 실행")
    p.add_argument("--demo-days", type=int, help="가상 데이터를 앞 N일로 잘라 실행 (짧은 데이터 모드 시연)")
    p.add_argument("--pos", help="POS 파일 경로 (실데이터)")
    p.add_argument("--pos-type", default="auto", choices=["auto", "toss", "okpos", "items"])
    p.add_argument("--address", help="매장 주소 → 위치를 찾아 날씨·행사·뉴스를 자동 수집 (store.json에 저장)")
    p.add_argument("--close-time", help="영업 종료 시각 HH:MM (store.json이 없을 때만 씀, 기본 21:00)")
    p.add_argument("--signals", help="[개발용] 외부 신호 파일 (SignalRow 형식 .json/.csv). 주면 자동 수집을 하지 않음")
    p.add_argument("--collection", help="[개발용] AI 주의 안내용 원문 모음 (CollectionItem 형식 .json)")
    p.add_argument("--from-step", default="ingest", choices=STEPS, help="이 단계부터 실행")
    p.add_argument("--iterations", type=int, help="[개발용] CatBoost 반복 수 (테스트를 빨리 돌릴 때)")
    p.add_argument("--artifacts", default=str(ARTIFACTS), help=argparse.SUPPRESS)   # 테스트용 결과 폴더
    args = p.parse_args(argv)
    args.model_kwargs = {"iterations": args.iterations} if args.iterations else {}
    return args


def main(argv=None) -> Path:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")                   # 오류 메시지(SystemExit)는 stderr로 나간다
    args = parse_args(argv)
    out = Path(args.artifacts) / args.store
    start_all = time.perf_counter()
    progress.reset()
    for step in STEPS[STEPS.index(args.from_step):]:
        t = time.perf_counter()
        progress.emit("step", step=step, status="start")
        note = STEP_FUNCS[step](args, out)
        progress.emit("step", step=step, status="done", note=note)
        print(f"[{step:<8}] {time.perf_counter() - t:5.1f}초  {note}")
    if args.from_step == "ingest":                             # 처음부터 돌린 실행만 남긴다 (준비 방식만 바꾼 실행은 덮어쓰지 않음)
        progress.save(out / PROGRESS_FILE)
    print(f"완료 {time.perf_counter() - start_all:.1f}초 → {out}")
    return out


if __name__ == "__main__":
    main()
