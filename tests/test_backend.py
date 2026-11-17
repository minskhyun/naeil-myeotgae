"""backend/app/main.py 테스트: 조회·입력 검사·실행 작업 (LLM은 부르지 않음)."""
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import main

EXAMPLES = Path(__file__).resolve().parents[1] / "contracts" / "examples"


@pytest.fixture
def client(tmp_path, monkeypatch):
    store = tmp_path / "sinchon-a"
    store.mkdir()
    for name in ("forecast.json", "backtest.json", "sources_report.json"):
        shutil.copyfile(EXAMPLES / name, store / name)
    (store / "store.json").write_text('{"store_id": "sinchon-a", "close_time": "21:00"}', encoding="utf-8")
    monkeypatch.setattr(main, "ARTIFACTS", tmp_path)
    monkeypatch.setattr(main, "UPLOADS", tmp_path / "uploads")
    return TestClient(main.app)


def test_read_endpoints(client):
    assert client.get("/api/health").json() == {"ok": True}
    assert [s["store_id"] for s in client.get("/api/stores").json()] == ["sinchon-a"]
    fc = client.get("/api/stores/sinchon-a/forecast").json()
    assert fc["store_id"] == "sinchon-a" and fc["rows"]
    assert client.get("/api/stores/sinchon-a/backtest").json()["chosen_model"]
    assert client.get("/api/stores/sinchon-a/sources").json()["signals"]


def test_bad_inputs(client):
    assert client.get("/api/stores/nowhere/forecast").status_code == 404
    assert client.get("/api/stores/..%2Fsecret/forecast").status_code in (400, 404)
    assert client.get("/api/stores/Bad_ID/forecast").status_code == 400
    assert client.post("/api/stores/sinchon-a/settings", data={"prep_mode": "많이"}).status_code == 400
    r = client.post("/api/stores/sinchon-a/run", files={"pos": ("pos.txt", b"x", "text/plain")})
    assert r.status_code == 400
    assert client.get("/api/jobs/없는작업").status_code == 404


def test_run_job_finishes(client, tmp_path):
    """가상 35일로 run.py를 별도 프로세스로 끝까지 돌리고, 작업 상태와 결과 파일을 확인한다."""
    job = main._start("sinchon-a", ["--demo", "--demo-days", "35", "--iterations", "30"])
    for _ in range(240):
        status = client.get(f"/api/jobs/{job['job_id']}").json()
        if status["status"] != "running":
            break
        time.sleep(0.5)
    assert status["status"] == "done", status
    assert any("predict" in line for line in status["log"])
    assert client.get("/api/stores/sinchon-a/forecast").json()["rows"][0]["date"] == "2025-12-06"
    assert "sinchon-a" not in main.RUNNING


def test_demo_mode_is_read_only(client, monkeypatch):
    """시연 모드: 보기는 되고, 업로드·실행·설정 변경은 403. 저장소의 시연 결과 폴더가 계약 형식을 지킨다."""
    monkeypatch.setattr(main, "DEMO_MODE", True)
    assert client.get("/api/config").json() == {"demo_mode": True}
    assert client.get("/api/stores/sinchon-a/forecast").status_code == 200
    assert client.post("/api/stores/sinchon-a/demo").status_code == 403
    assert client.post("/api/stores/sinchon-a/settings", data={"prep_mode": "균형"}).status_code == 403
    r = client.post("/api/stores/sinchon-a/run", files={"pos": ("pos.csv", b"x", "text/csv")})
    assert r.status_code == 403


def test_demo_data_follows_contracts():
    from contracts.schemas import BacktestResult, Forecast, SourceReport
    folder = Path(main.__file__).resolve().parents[1] / "demo_data"
    stores = sorted(d.name for d in folder.iterdir() if d.is_dir())
    assert stores == ["fr-bakery", "sinchon-a"]
    for s in stores:
        Forecast.model_validate_json((folder / s / "forecast.json").read_text(encoding="utf-8"))
        SourceReport.model_validate_json((folder / s / "sources_report.json").read_text(encoding="utf-8"))
        BacktestResult.model_validate_json((folder / s / "backtest.json").read_text(encoding="utf-8"))
