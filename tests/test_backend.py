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
    monkeypatch.setattr(main.auth, "CLIENT_ID", None)             # 로그인 꺼짐 (켜진 경우는 tests/test_auth.py)
    monkeypatch.setattr(main.auth, "KAKAO_KEY", None)
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
    assert not any(line.startswith("@@EVENT") for line in status["log"])       # 알림 줄은 실행 기록에 섞이지 않고
    kinds = [e["kind"] for e in status["events"]]                               # 알림으로 따로 온다 (화면의 분석 과정)
    assert kinds[0] == "step" and {"sales", "decision", "forecast"} <= set(kinds)
    replay = client.get("/api/stores/sinchon-a/progress").json()                # 끝난 뒤에는 다시 볼 수 있게 저장된다
    assert [e["kind"] for e in replay] == kinds
    assert client.get("/api/stores/sinchon-a/forecast").json()["rows"][0]["date"] == "2025-12-06"
    assert "sinchon-a" not in main.RUNNING


def test_demo_mode_is_read_only(client, monkeypatch):
    """시연 모드: 보기는 되고, 업로드·실행·설정 변경은 403. 저장소의 시연 결과 폴더가 계약 형식을 지킨다."""
    monkeypatch.setattr(main, "DEMO_MODE", True)
    assert client.get("/api/config").json() == {"demo_mode": True, "google_client_id": None, "kakao_login": False,
                                                "contact_url": None}
    assert client.get("/api/stores/sinchon-a/forecast").status_code == 200
    assert client.post("/api/stores/sinchon-a/demo").status_code == 403
    assert client.post("/api/stores/sinchon-a/settings", data={"prep_mode": "균형"}).status_code == 403
    r = client.post("/api/stores/sinchon-a/run", files={"pos": ("pos.csv", b"x", "text/csv")})
    assert r.status_code == 403


def test_app_page_serves_the_same_screen_file():
    """화면의 주소는 셋이다: "/" 첫 화면, "/about" 소개, "/app" 분석 화면. 서버는 모두 같은 화면 파일을 준다 (어느 화면인지는 화면 코드가 정한다)."""
    if not main.WEB_DIST.exists():
        pytest.skip("화면을 빌드하지 않았다 (frontend/dist 없음)")
    client = TestClient(main.app)
    home, app_page = client.get("/"), client.get(main.APP_PAGE)
    assert app_page.status_code == 200 and "text/html" in app_page.headers["content-type"]
    assert app_page.text == home.text
    assert client.get(main.ABOUT_PAGE).text == home.text

def test_demo_data_follows_contracts():
    from contracts.schemas import BacktestResult, Forecast, SalesHistory, SourceReport
    folder = Path(main.__file__).resolve().parents[1] / "demo_data"
    stores = sorted(d.name for d in folder.iterdir() if d.is_dir())
    assert stores == ["fr-bakery", "sinchon-a"]
    for s in stores:
        Forecast.model_validate_json((folder / s / "forecast.json").read_text(encoding="utf-8"))
        SourceReport.model_validate_json((folder / s / "sources_report.json").read_text(encoding="utf-8"))
        BacktestResult.model_validate_json((folder / s / "backtest.json").read_text(encoding="utf-8"))
        SalesHistory.model_validate_json((folder / s / "history.json").read_text(encoding="utf-8"))    # 준비표 그래프의 재료
    import json                                                                 # 첫 화면의 '분석 과정 보기'가 재생하는 녹화본
    kinds = [e["kind"] for e in json.loads((folder / "sinchon-a" / "progress.json").read_text(encoding="utf-8"))]
    assert {"store", "places", "plan", "trial", "decision", "scores", "forecast"} <= set(kinds)


def test_history_endpoint_serves_chart_data():
    """준비표 그래프의 재료: 시연 매장은 history.json 그대로 (최근 4주, 예측한 메뉴들)."""
    r = TestClient(main.app).get("/api/stores/sinchon-a/history")
    assert r.status_code == 200
    body = r.json()
    assert len(body["dates"]) == 28 == len(body["total"]) and "소금빵" in body["menus"]
