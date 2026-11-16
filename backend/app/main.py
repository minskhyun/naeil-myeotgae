"""내일몇개 백엔드 (FastAPI): 예측 결과를 화면에 주고, POS를 올리면 예측을 돌린다.

    uvicorn backend.app.main:app --reload --port 8000          (프로젝트 맨 위 폴더에서)
    → http://localhost:8000/docs 에서 API를 눌러 볼 수 있다

조회
  GET  /api/health                         살아 있는지
  GET  /api/stores                         결과가 있는 매장 목록
  GET  /api/stores/{store_id}/forecast     내일 예측 (contracts.Forecast)
  GET  /api/stores/{store_id}/backtest     모델 비교·신호 채택 (contracts.BacktestResult)
실행 (오래 걸리므로 작업 번호를 주고, 화면이 상태를 물어본다)
  POST /api/stores/{store_id}/run          POS 파일(+선택: 신호·원문 파일) 업로드 → run.py 전체 실행
  POST /api/stores/{store_id}/demo         가상 데이터로 전체 실행 (시연용)
  POST /api/stores/{store_id}/settings     준비 방식 바꾸기 → predict 단계만 다시
  GET  /api/jobs/{job_id}                  작업 상태 (running / done / error) + 실행 기록

예측 계산은 run.py를 '별도 프로세스'로 실행한다. 서버가 멈추지 않고, 명령줄에서 돌린 것과 결과가 똑같다.

시연 모드 (클라우드 공개용):  DEMO_MODE=1
  - 보기 전용: 업로드·실행·설정 변경은 403. 예측도 LLM도 돌리지 않으므로 API 키가 필요 없다.
  - 결과는 backend/demo_data/ (가상 매장·공개 데이터 결과만, 저장소에 들어 있음)
  - frontend/dist가 있으면 화면도 이 서버가 함께 보여 준다 → 주소 하나로 끝 (Dockerfile 참고)
"""
import json
import os
import re
import subprocess
import sys
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from contracts.schemas import BacktestResult, Forecast
from ml.predict import PREP_MODES

ROOT = Path(__file__).resolve().parents[2]
DEMO_MODE = os.environ.get("DEMO_MODE") == "1"   # 보기 전용 (클라우드 공개용)
# 결과 폴더: 시연 모드면 저장소에 든 시연 결과, 아니면 data/artifacts (테스트에서 바꿔 끼운다)
ARTIFACTS = ROOT / "backend" / "demo_data" if DEMO_MODE else ROOT / "data" / "artifacts"
WEB_DIST = ROOT / "frontend" / "dist"            # npm run build 결과 (있으면 화면도 함께 제공)
UPLOADS = ROOT / "data" / "raw" / "uploads"      # 올린 파일 (실제 매장 자료 → 커밋 안 됨)
STORE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")   # 폴더 이름으로 쓰므로 안전한 글자만

app = FastAPI(title="내일몇개 API")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])

JOBS: dict[str, dict] = {}            # 작업 번호 → {status, store_id, log, error}
RUNNING: set[str] = set()             # 지금 실행 중인 매장 (같은 매장은 한 번에 하나만)
LOCK = threading.Lock()


# ---------------------------------------------------------------- 조회

def _store_dir(store_id: str) -> Path:
    if not STORE_ID.match(store_id):
        raise HTTPException(400, "매장 ID는 영어 소문자·숫자·하이픈만 쓸 수 있습니다 (예: seongsu-a).")
    return ARTIFACTS / store_id


def _read(store_id: str, name: str) -> str:
    path = _store_dir(store_id) / name
    if not path.exists():
        raise HTTPException(404, f"{store_id}의 {name}이(가) 없습니다. 먼저 예측을 실행하세요.")
    return path.read_text(encoding="utf-8")


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/config")
def config():
    """화면이 처음에 물어본다: 시연 모드면 '데이터 올리기'와 준비 방식 바꾸기를 숨긴다."""
    return {"demo_mode": DEMO_MODE}


@app.get("/api/stores")
def stores():
    out = []
    for d in sorted(ARTIFACTS.glob("*/forecast.json")):
        info_path = d.parent / "store.json"
        info = json.loads(info_path.read_text(encoding="utf-8")) if info_path.exists() else {}
        out.append(dict(store_id=d.parent.name, name=info.get("name", d.parent.name),
                        prep_mode=info.get("prep_mode", "균형"), close_time=info.get("close_time"),
                        has_backtest=(d.parent / "backtest.json").exists(), running=d.parent.name in RUNNING))
    return out


@app.get("/api/stores/{store_id}/forecast", response_model=Forecast)
def forecast(store_id: str):
    return Forecast.model_validate_json(_read(store_id, "forecast.json"))


@app.get("/api/stores/{store_id}/backtest", response_model=BacktestResult)
def backtest(store_id: str):
    return BacktestResult.model_validate_json(_read(store_id, "backtest.json"))


# ---------------------------------------------------------------- 실행

def _start(store_id: str, args: list[str]) -> dict:
    """run.py를 별도 프로세스로 시작하고 작업 번호를 돌려준다."""
    if DEMO_MODE:
        raise HTTPException(403, "시연용 화면에서는 예측을 새로 돌릴 수 없습니다.")
    with LOCK:
        if store_id in RUNNING:
            raise HTTPException(409, f"{store_id}는 이미 실행 중입니다. 끝난 뒤 다시 시도하세요.")
        RUNNING.add(store_id)
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = dict(job_id=job_id, store_id=store_id, status="running", log=[], error=None)
    cmd = [sys.executable, str(ROOT / "run.py"), "--store", store_id, "--artifacts", str(ARTIFACTS), *args]

    def work():
        job = JOBS[job_id]
        try:
            proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding="utf-8", errors="replace")
            for line in proc.stdout:                       # 단계마다 한 줄씩 → 화면에 진행 상황
                job["log"].append(line.rstrip())
            proc.wait()
            if proc.returncode == 0:
                job["status"] = "done"
            else:
                job["status"] = "error"
                job["error"] = next((l for l in reversed(job["log"]) if l.strip()), "알 수 없는 오류")
        except Exception as e:                             # 실행 자체가 안 될 때
            job.update(status="error", error=f"{type(e).__name__}: {e}")
        finally:
            RUNNING.discard(store_id)

    threading.Thread(target=work, daemon=True).start()
    return JOBS[job_id]


def _save(upload: UploadFile, folder: Path, name: str) -> Path:
    suffix = Path(upload.filename or "").suffix.lower()
    path = folder / f"{name}{suffix}"
    path.write_bytes(upload.file.read())
    return path


@app.post("/api/stores/{store_id}/run", status_code=202)
def run_store(store_id: str, pos: UploadFile = File(..., description="POS 엑셀·CSV (토스·OKPOS)"),
              signals: UploadFile | None = File(None, description="외부 신호 .json/.csv (선택)"),
              collection: UploadFile | None = File(None, description="LLM 경고용 원문 .json (선택)"),
              close_time: str | None = Form(None, description="영업 종료 시각 HH:MM (처음 한 번만 쓰임)")):
    _store_dir(store_id)
    if DEMO_MODE:
        raise HTTPException(403, "시연용 화면에서는 파일을 올릴 수 없습니다.")
    if Path(pos.filename or "").suffix.lower() not in (".xlsx", ".xls", ".xlsm", ".csv"):
        raise HTTPException(400, "POS 파일은 엑셀(.xlsx·.xls) 또는 .csv여야 합니다.")
    folder = UPLOADS / store_id
    folder.mkdir(parents=True, exist_ok=True)
    args = ["--pos", str(_save(pos, folder, "pos"))]
    if signals is not None and signals.filename:
        args += ["--signals", str(_save(signals, folder, "signals"))]
    if collection is not None and collection.filename:
        args += ["--collection", str(_save(collection, folder, "collection"))]
    if close_time:
        args += ["--close-time", close_time]
    return _start(store_id, args)


@app.post("/api/stores/{store_id}/demo", status_code=202)
def run_demo(store_id: str = "sinchon-a"):
    _store_dir(store_id)
    args = ["--demo"]
    sample_collection = ROOT / "data" / "sample" / store_id / "collection.json"
    if sample_collection.exists():
        args += ["--collection", str(sample_collection)]
    return _start(store_id, args)


@app.post("/api/stores/{store_id}/settings", status_code=202)
def settings(store_id: str, prep_mode: str = Form(...)):
    if DEMO_MODE:
        raise HTTPException(403, "시연용 화면에서는 설정을 바꿀 수 없습니다.")
    if prep_mode not in PREP_MODES:
        raise HTTPException(400, f"준비 방식은 {list(PREP_MODES)} 중 하나여야 합니다.")
    path = _store_dir(store_id) / "store.json"
    if not path.exists():
        raise HTTPException(404, f"{store_id}의 store.json이 없습니다. 먼저 예측을 실행하세요.")
    info = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**info, "prep_mode": prep_mode}, ensure_ascii=False, indent=1), encoding="utf-8")
    return _start(store_id, ["--from-step", "predict"])


@app.get("/api/jobs/{job_id}")
def job(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(404, "그런 작업이 없습니다 (서버를 다시 켜면 작업 기록은 사라집니다).")
    return JOBS[job_id]


# 빌드된 화면 (맨 마지막에 둔다: /api/... 가 먼저 처리되고, 나머지 주소는 화면 파일)
if WEB_DIST.exists():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
