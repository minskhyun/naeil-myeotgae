"""한 매장 전체 실행: ingest → evaluate → predict  (TASKS.md §12)

    python run.py --store sinchon-a --demo                          # 가상 데이터로 끝까지
    python run.py --store sinchon-a --demo --demo-days 35           # 가상 데이터를 35일로 잘라 '짧은 데이터 모드' 시연
    python run.py --store seongsu-a --pos data/raw/seongsu-a.xlsx \\
                  --address "서울 성동구 성수이로 113"              # 실데이터: 주소로 날씨·기념일 자동 수집
    python run.py --store seongsu-a --pos data/raw/seongsu-a.xlsx \\
                  --signals data/raw/seongsu-a_signals.json        # 신호 파일을 직접 줄 때 (자동 수집 안 함)
    python run.py --store seongsu-a --from-step predict             # 앞 단계 결과 파일을 그대로 쓰고 predict만

결과는 모두 data/artifacts/{store_id}/ 에 쌓인다 (이 폴더는 .gitignore 대상, 커밋되지 않음).
    store.json         매장 설정 (영업 종료 시각, 준비 방식, 주소·위도·경도, 선택: 지금 파는 메뉴 목록 "menus")
    sales_clean.csv    ingest 결과 (SalesRow 형식)
    signals.csv        외부 신호 (있으면)
    backtest.json      evaluate 결과 (BacktestResult)
    forecast.json      predict 결과 (Forecast)
"""
import argparse
import json
import shutil
import sys
import time
from pathlib import Path

import pandas as pd

from agent.weather import OBSERVED_PROXY
from contracts.schemas import BacktestResult, CollectionItem, SignalRow
from ml.alerts import make_warnings
from ml.evaluate import ARTIFACTS, ROOT, run_backtest, write_backtest
from ml.features import DEFAULT_CLOSE_TIME, load_sales, load_signals
from ml.predict import predict_from_backtest, write_forecast

SAMPLE_ROOT = ROOT / "data" / "sample"
STEPS = ["ingest", "evaluate", "predict"]


def _need(path: Path, step: str) -> Path:
    """다음 단계에 필요한 파일이 없으면, 무엇을 먼저 실행해야 하는지 알려 주고 멈춘다."""
    if not path.exists():
        raise SystemExit(f"{path.name}이(가) 없습니다: {path}\n→ '{step}' 단계부터 실행하세요 (--from-step {step}).")
    return path


def _store_info(out: Path) -> dict:
    return json.loads(_need(out / "store.json", "ingest").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 단계

def step_ingest(args, out: Path) -> str:
    out.mkdir(parents=True, exist_ok=True)
    if args.demo:
        src = SAMPLE_ROOT / args.store
        if not (src / "sales.csv").exists():
            raise SystemExit(f"가상 데이터가 없습니다: {src}  (python -m ml.sample_data 로 만드세요)")
        sales = load_sales(src / "sales.csv")
        if args.demo_days:                                    # 앞 N일만 남겨 짧은 데이터 상황을 흉내 낸다
            sales = sales[sales["date"] < sales["date"].min() + pd.Timedelta(days=args.demo_days)]
        sales.assign(date=sales["date"].dt.strftime("%Y-%m-%d")).to_csv(out / "sales_clean.csv", index=False,
                                                                         encoding="utf-8")
        shutil.copyfile(src / "signals.csv", out / "signals.csv")
        shutil.copyfile(src / "store.json", out / "store.json")
        note = f"가상 데이터 {sales['date'].nunique()}일, {len(sales)}행"
        if args.collection:
            note += ", " + _import_collection(Path(args.collection), out)
        return note

    if not args.pos:
        raise SystemExit("--demo 또는 --pos <POS 파일> 중 하나가 필요합니다.")
    from ml.ingest import ingest_store                         # 실데이터에서만 필요 (다음 단계에서 구현)
    note = ingest_store(Path(args.pos), args.store, out, pos_type=args.pos_type)
    info, where = _store_setup(args, out)
    if where:
        note += ", " + where
    # 주변 정보: 신호 파일을 직접 주면 그것을, 아니면 매장 위치로 자동 수집 (사장님은 POS만 올린다)
    if args.signals and Path(args.signals).resolve() != (out / "signals.csv").resolve():
        note += ", " + _import_signals(Path(args.signals), args.store, out)
    elif not args.signals:
        note += ", " + _auto_signals(args.store, out, info)
    # 행사·뉴스 원문: 직접 주거나, data/raw/{store}_collection.json이 있으면 자동으로 (수집기 events.py는 아직 없음)
    auto_collection = ROOT / "data" / "raw" / f"{args.store}_collection.json"
    if args.collection:
        note += ", " + _import_collection(Path(args.collection), out)
    elif auto_collection.exists():
        note += ", " + _import_collection(auto_collection, out) + " (data/raw에서 자동)"
    return note


def _store_setup(args, out: Path) -> tuple[dict, str]:
    """store.json을 만들거나 고친다 (영업 종료 시각, 주소 → 위도·경도). 돌려주는 값: (설정, 위치 메모)."""
    path = out / "store.json"
    info = json.loads(path.read_text(encoding="utf-8")) if path.exists() else \
        {"store_id": args.store, "close_time": args.close_time or DEFAULT_CLOSE_TIME, "prep_mode": "균형"}
    note = ""
    if args.lat is not None and args.lon is not None:
        info.update(lat=args.lat, lon=args.lon)
    if args.address and args.address != info.get("address"):
        from agent.geocode import geocode
        try:
            lat, lon, found = geocode(args.address)
            info.update(address=args.address, lat=round(lat, 5), lon=round(lon, 5))
            note = f"위치 {found.split(',')[0]} ({lat:.4f}, {lon:.4f})"
        except Exception as e:                                  # 위치를 못 찾아도 예측은 계속 (날씨 없이)
            note = f"주소로 위치를 찾지 못함({type(e).__name__}) → 날씨 없이 진행"
    path.write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    return info, note


def _auto_signals(store_id: str, out: Path, info: dict) -> str:
    """매장 위치로 날씨(과거=관측 대용, 앞으로=실제 예보)·기념일을 모아 signals.csv로. 실패해도 예측은 계속."""
    if "lat" not in info or "lon" not in info:
        return "주변 정보 없음 (매장 위치를 모름: 주소를 넣으면 날씨를 자동으로 붙임)"
    from agent.build import collect
    from ml.alerts import settings
    key = settings().get("DATA_GO_KR_KEY")
    if not key:
        return "주변 정보 없음 (.env에 DATA_GO_KR_KEY가 없음)"
    start = load_sales(out / "sales_clean.csv")["date"].min() - pd.Timedelta(days=35)   # 기온 '최근 28일 평균'용 여유
    try:
        rows = collect(store_id, info["lat"], info["lon"], start.strftime("%Y%m%d"), key)
    except Exception as e:
        return f"날씨 자동 수집 실패({type(e).__name__}: {str(e)[:80]}) → 주변 정보 없이 진행"
    sig = pd.DataFrame([r.model_dump() for r in rows])
    return "날씨·기념일 자동 수집 " + _write_signals(sig, store_id, out, "자동 수집")


def _import_signals(path: Path, store_id: str, out: Path) -> str:
    """신호 파일(.json/.csv) → 계약(SignalRow) 검사 → 이 매장 것만 out/signals.csv로 저장."""
    return _write_signals(load_signals(path), store_id, out, path.name)


def _write_signals(sig: pd.DataFrame, store_id: str, out: Path, source: str) -> str:
    for rec in sig.to_dict("records"):                          # 한 줄이라도 형식이 틀리면 여기서 멈춘다
        SignalRow.model_validate(rec)
    mine = sig[sig["store_id"] == store_id]
    if mine.empty:
        raise SystemExit(f"{source}에 store_id='{store_id}'인 신호가 없습니다 (있는 매장: {sorted(set(sig['store_id']))}).")
    mine.to_csv(out / "signals.csv", index=False, encoding="utf-8")
    note = f"신호 {len(mine)}행 ({', '.join(sorted(set(mine['signal'])))})"
    proxy = int(mine["source_url"].str.contains(OBSERVED_PROXY, regex=False).sum())
    if proxy:                                                   # 실제 예보가 아닌 줄 → 결과를 말할 때 밝혀야 함
        note += f" ※ 관측값을 예보 대신 쓴 줄 {proxy}행: 검증 성능이 실제보다 조금 좋게 나올 수 있음"
    return note


def _import_collection(path: Path, out: Path) -> str:
    """원문 모음(.json, CollectionItem 목록) → 형식 검사 → 공개 시각을 한국 시간으로 → out/collection.json."""
    items = []
    for i, rec in enumerate(json.loads(path.read_text(encoding="utf-8-sig"))):
        try:
            item = CollectionItem.model_validate(rec)
        except ValueError as e:
            raise SystemExit(f"{path.name}의 {i}번째 항목 형식이 틀립니다:\n{e}")
        if item.published_at is not None and item.published_at.tzinfo is not None:
            item.published_at = (pd.Timestamp(item.published_at).tz_convert("Asia/Seoul")
                                 .tz_localize(None).to_pydatetime())
        items.append(item.model_dump(mode="json"))
    (out / "collection.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    return f"원문 {len(items)}개"


def _load(out: Path):
    sales = load_sales(_need(out / "sales_clean.csv", "ingest"))
    signals = load_signals(out / "signals.csv") if (out / "signals.csv").exists() else None
    return sales, signals


def step_evaluate(args, out: Path) -> str:
    info = _store_info(out)
    sales, signals = _load(out)
    bt = run_backtest(sales, signals, close_time=info.get("close_time", DEFAULT_CLOSE_TIME), **args.model_kwargs)
    write_backtest(bt, out.parent)
    adopted = [d.signal_group for d in bt.decisions if d.adopted] or ["없음"]
    return f"선택 모델 {bt.chosen_model}, 채택 신호 {', '.join(adopted)}"


def step_predict(args, out: Path) -> str:
    info = _store_info(out)
    sales, signals = _load(out)
    bt = BacktestResult.model_validate_json(_need(out / "backtest.json", "evaluate").read_text(encoding="utf-8"))
    menus = info.get("menus")                                  # 선택: 지금 파는 메뉴 목록 (없으면 최근 14일 판매 메뉴 전부)
    fc = predict_from_backtest(sales, signals, bt, close_time=info.get("close_time", DEFAULT_CLOSE_TIME),
                               prep_mode=info.get("prep_mode", "균형"), menus=menus, **args.model_kwargs)
    note = ""
    if menus is not None:                                      # 오타·아직 안 판 신메뉴는 예측할 수 없으니 알려 준다
        missing = sorted(set(menus) - {r.menu for r in fc.rows})
        if missing:
            note += f", menus 중 예측 못 한 메뉴(최근 14일 판매 기록 없음·오타?): {', '.join(missing)}"
    if (out / "collection.json").exists():                    # 새얼이 모은 자료가 있으면 LLM 경고 (숫자는 안 바꿈)
        try:
            collection = json.loads((out / "collection.json").read_text(encoding="utf-8"))
            fc.warnings = make_warnings(fc, collection, out / "llm_cache",
                                        close_time=info.get("close_time", DEFAULT_CLOSE_TIME))
            note += f", 경고 {len(fc.warnings)}개"
        except Exception as e:                                # 경고는 부가 기능: 실패해도 예측은 저장
            note += f", 경고 생성 실패({type(e).__name__}) → 경고 없이 저장"
    write_forecast(fc, out.parent)
    return f"{fc.rows[0].date} 메뉴 {len(fc.rows)}개 예측{note}"


STEP_FUNCS = {"ingest": step_ingest, "evaluate": step_evaluate, "predict": step_predict}


# ---------------------------------------------------------------- 실행

def parse_args(argv=None):
    p = argparse.ArgumentParser(description="내일몇개 예측 엔진: 한 매장 전체 실행")
    p.add_argument("--store", required=True, help="매장 ID (예: sinchon-a)")
    p.add_argument("--demo", action="store_true", help="data/sample/{store}의 가상 데이터로 실행")
    p.add_argument("--demo-days", type=int, help="가상 데이터를 앞 N일로 잘라 실행 (짧은 데이터 모드 시연)")
    p.add_argument("--pos", help="POS 파일 경로 (실데이터)")
    p.add_argument("--pos-type", default="auto", choices=["auto", "toss", "okpos"])
    p.add_argument("--address", help="매장 주소 → 위치를 찾아 날씨·기념일을 자동 수집 (store.json에 저장)")
    p.add_argument("--lat", type=float, help="매장 위도 (주소 대신)")
    p.add_argument("--lon", type=float, help="매장 경도 (주소 대신)")
    p.add_argument("--signals", help="외부 신호 파일 (SignalRow 형식 .json 또는 .csv). 주면 자동 수집을 하지 않음")
    p.add_argument("--collection", help="LLM 경고용 원문 모음 (CollectionItem 형식 .json, 선택)")
    p.add_argument("--close-time", help="영업 종료 시각 (store.json이 없을 때만 씀, 기본 21:00)")
    p.add_argument("--from-step", default="ingest", choices=STEPS, help="이 단계부터 실행")
    p.add_argument("--iterations", type=int, help="CatBoost 반복 수 (테스트용, 보통은 비워 둠)")
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
    for step in STEPS[STEPS.index(args.from_step):]:
        t = time.perf_counter()
        note = STEP_FUNCS[step](args, out)
        print(f"[{step:<8}] {time.perf_counter() - t:5.1f}초  {note}")
    print(f"완료 {time.perf_counter() - start_all:.1f}초 → {out}")
    return out


if __name__ == "__main__":
    main()
