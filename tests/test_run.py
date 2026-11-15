"""run.py 전체 실행 테스트 (TASKS.md §4: 전체 실행 테스트·짧은 데이터 테스트)."""
import json

import pandas as pd
import pytest

from contracts.schemas import BacktestResult, Forecast, SalesRow
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
