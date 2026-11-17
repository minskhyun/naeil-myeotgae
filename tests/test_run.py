"""run.py 전체 실행 테스트 (TASKS.md §4: 전체 실행 테스트·짧은 데이터 테스트)."""
import json
from pathlib import Path

import pandas as pd
import pytest

from contracts.schemas import BacktestResult, Forecast, SalesRow, SignalRow
from run import main


def _check_outputs(out):
    """결과 파일 3개가 계약 형식을 통과하는지."""
    sales = pd.read_csv(out / "sales_clean.csv")
    for rec in sales.to_dict("records"):
        SalesRow.model_validate(rec)
    bt = BacktestResult.model_validate_json((out / "backtest.json").read_text(encoding="utf-8"))
    fc = Forecast.model_validate_json((out / "forecast.json").read_text(encoding="utf-8"))
    return bt, fc


def test_demo_end_to_end(tmp_path):
    out = main(["--store", "sinchon-a", "--demo", "--iterations", "50", "--artifacts", str(tmp_path)])
    bt, fc = _check_outputs(out)
    assert bt.test_period is not None and fc.rows

    # --from-step predict: 앞 단계 파일을 그대로 쓰고 예측만 다시
    before = (out / "backtest.json").stat().st_mtime_ns
    main(["--store", "sinchon-a", "--from-step", "predict", "--iterations", "50", "--artifacts", str(tmp_path)])
    assert (out / "backtest.json").stat().st_mtime_ns == before          # evaluate는 다시 돌지 않음

    # store.json에 지금 파는 메뉴 목록을 적으면 그 메뉴만 예측 (오타는 건너뜀)
    info = json.loads((out / "store.json").read_text(encoding="utf-8"))
    (out / "store.json").write_text(json.dumps({**info, "menus": ["소금빵", "베이글", "소금뻥"]}, ensure_ascii=False),
                                    encoding="utf-8")
    main(["--store", "sinchon-a", "--from-step", "predict", "--iterations", "50", "--artifacts", str(tmp_path)])
    _, fc = _check_outputs(out)
    assert {r.menu for r in fc.rows} == {"소금빵", "베이글"}


def test_demo_short_data(tmp_path):
    out = main(["--store", "sinchon-a", "--demo", "--demo-days", "35", "--iterations", "50",
                "--artifacts", str(tmp_path)])
    bt, fc = _check_outputs(out)
    assert "판매 기록 35일" in bt.data_note
    assert str(fc.rows[0].date) == "2025-12-06"                         # 35일째 다음 날


def test_missing_previous_step_is_explained(tmp_path):
    with pytest.raises(SystemExit, match="ingest"):
        main(["--store", "nowhere", "--from-step", "evaluate", "--artifacts", str(tmp_path)])


def _fake_collect(store, start, end, **kw):
    """실제 수집 대신: 기간 안의 날마다 '전날 17:10 예보' 기온·강수 + 소금빵의 검색량 유행 (인터넷 없이)."""
    days = pd.date_range(pd.Timestamp(start), "2026-11-02")
    weather = [SignalRow(date=d.date(), store_id=store.store_id, signal=sig, value=v, source_url="https://test",
                         published_at=d - pd.Timedelta(hours=6, minutes=50), kind="forecast")
               for d in days for sig, v in (("temp_mean", 10.0 + d.month), ("rain_mm", float(d.day % 5 == 0) * 3))]
    trend = [SignalRow(date=d.date(), store_id=store.store_id, signal="trend_level", menu="소금빵",
                       value=1.0 + (d.day % 7) / 10, source_url="https://test",
                       published_at=d - pd.Timedelta(hours=15), kind="observed") for d in days]
    return weather + trend, [], ["가짜"]


def test_address_collects_weather_automatically(tmp_path, monkeypatch):
    """사장님은 POS와 주소만 준다 → 위치를 찾아 store.json에 적고, 날씨와 메뉴별 유행 신호를 자동으로 붙인다."""
    import agent.collect
    import agent.geocode
    monkeypatch.setattr(agent.geocode, "geocode", lambda a: (37.5365, 127.0539, "성수동2가, 성동구, 서울"))
    monkeypatch.setattr(agent.collect, "collect_all", _fake_collect)
    pos = Path(__file__).resolve().parents[1] / "data" / "sample" / "sinchon-a" / "pos_raw.csv"
    out = main(["--store", "test-a", "--pos", str(pos), "--address", "서울 성동구 성수이로 113",
                "--iterations", "30", "--artifacts", str(tmp_path)])
    info = json.loads((out / "store.json").read_text(encoding="utf-8"))
    assert info["address"] == "서울 성동구 성수이로 113" and info["lat"] == 37.5365
    sig = pd.read_csv(out / "signals.csv")
    assert set(sig["signal"]) == {"temp_mean", "rain_mm", "trend_level"} and (sig["store_id"] == "test-a").all()
    assert set(sig.loc[sig["signal"] == "trend_level", "menu"]) == {"소금빵"} and sig.loc[sig["signal"] == "rain_mm", "menu"].isna().all()
    bt = BacktestResult.model_validate_json((out / "backtest.json").read_text(encoding="utf-8"))
    for group in ("weather", "trend"):                                                    # 날씨와 유행이 평가에 들어감
        assert any(d.signal_group == group and d.folds_total > 0 for d in bt.decisions), group
    report = json.loads((out / "sources_report.json").read_text(encoding="utf-8"))        # 화면 '주변 정보'용 요약
    by_signal = {s["signal"]: s for s in report["signals"]}
    assert set(by_signal) == {"temp_mean", "rain_mm", "trend_level"} and report["notes"] == ["가짜"]
    assert by_signal["trend_level"]["n_menus"] == 1 and by_signal["rain_mm"]["n_menus"] == 0


def test_without_address_runs_without_signals(tmp_path, capsys):
    pos = Path(__file__).resolve().parents[1] / "data" / "sample" / "sinchon-a" / "pos_raw.csv"
    out = main(["--store", "test-b", "--pos", str(pos), "--iterations", "30", "--artifacts", str(tmp_path)])
    assert not (out / "signals.csv").exists() and (out / "forecast.json").exists()
    assert "주변 정보 없음" in capsys.readouterr().out
