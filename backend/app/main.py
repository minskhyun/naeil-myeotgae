"""내일몇개 백엔드 (FastAPI): 예측 결과를 화면에 주고, POS를 올리면 예측을 돌린다.

    uvicorn backend.app.main:app --reload --port 8000          (프로젝트 맨 위 폴더에서)
    → http://localhost:8000/docs 에서 API를 눌러 볼 수 있다

조회
  GET  /api/health                         살아 있는지
  GET  /api/config                         시연 모드인지, 로그인을 쓰는지
  GET  /api/stores                         내가 볼 수 있는 매장 목록
  GET  /api/stores/{store_id}/forecast     내일 예측 (contracts.Forecast)
  GET  /api/stores/{store_id}/backtest     모델 비교·신호 채택 (contracts.BacktestResult)
  GET  /api/stores/{store_id}/sources      주변 정보를 어디서 왜 무엇을 모았는지 (contracts.SourceReport)
실행 (오래 걸리므로 작업 번호를 주고, 화면이 상태를 물어본다)
  POST /api/stores/{store_id}/run          POS 파일 + 매장 주소 → run.py 전체 실행 (주변 정보는 주소로 자동 수집)
  POST /api/stores/{store_id}/demo         가상 데이터로 전체 실행 (시연용)
  POST /api/stores/{store_id}/settings     준비 방식 바꾸기 → predict 단계만 다시
  GET  /api/jobs/{job_id}                  작업 상태 (running / done / error) + 실행 기록
로그인 (.env에 GOOGLE_CLIENT_ID 또는 KAKAO_LOGIN=1이 있을 때만 켜진다 → backend/app/auth.py)
  POST /api/auth/google                    구글이 준 토큰을 확인하고 로그인 쿠키를 준다
  GET  /api/auth/kakao/start               카카오 로그인 화면으로 보낸다
  GET  /api/auth/kakao/callback            카카오가 돌려보내는 곳: 확인하고 로그인 쿠키를 준 뒤 첫 화면으로
  GET  /api/auth/me                        지금 로그인한 사람 (없으면 null)
  POST /api/auth/logout                    로그아웃
  로그인이 켜지면: 시연 매장은 누구나 보고, 내 매장은 나만 보고 고친다. 파일 올리기는 로그인해야 한다.
내 매장 관리 (로그인한 사람만)
  GET    /api/my/stores                    내 매장 목록 (아직 준비표가 없는 매장도)
  POST   /api/my/stores                    새 매장 만들기 (이름, 영업 종료 시각) → 서버가 매장 ID를 지어 준다
  PATCH  /api/my/stores/{store_id}         이름 바꾸기
  DELETE /api/my/stores/{store_id}         매장과 그 자료(올린 파일, 결과)를 모두 지우기

예측 계산은 run.py를 '별도 프로세스'로 실행한다. 서버가 멈추지 않고, 명령줄에서 돌린 것과 결과가 똑같다.
→ 예측 로직을 고칠 때 이 파일은 건드릴 필요가 없다.

시연 모드 (클라우드 공개용):  DEMO_MODE=1
  - 보기 전용: 업로드·실행·설정 변경은 403. 예측도 LLM도 돌리지 않으므로 API 키가 필요 없다.
  - 결과는 backend/demo_data/ (가상 매장·공개 데이터 결과만, 저장소에 들어 있음)
  - frontend/dist가 있으면 화면도 이 서버가 함께 보여 준다 → 주소 하나로 끝 (Dockerfile 참고)
"""
import datetime as dt
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.app import auth
from contracts.schemas import DEFAULT_CLOSE_TIME, BacktestResult, Forecast, SourceReport, StoreConfig
from ml import paths
from ml.predict import PREP_MODES

Me = Depends(auth.current_user)     # 요청을 보낸 사람 (로그인 안 했으면 None)

DEMO_MODE = os.environ.get("DEMO_MODE") == "1"   # 보기 전용 (클라우드 공개용)
# 결과 폴더: 시연 모드면 저장소에 든 시연 결과, 아니면 data/artifacts (테스트에서 바꿔 끼운다)
ARTIFACTS = paths.ROOT / "backend" / "demo_data" if DEMO_MODE else paths.ARTIFACTS
WEB_DIST = paths.ROOT / "frontend" / "dist"      # npm run build 결과 (있으면 화면도 함께 제공)
UPLOADS = paths.RAW / "uploads"                  # 올린 파일 (실제 매장 자료 → 커밋 안 됨)
STORE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")   # 폴더 이름으로 쓰므로 안전한 글자만
POS_SUFFIXES = (".xlsx", ".xls", ".xlsm", ".csv")
CLOSE_TIME = r"^([01]\d|2[0-3]):[0-5]\d$"            # 영업 종료 시각 HH:MM

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


def _read(store_id: str, name: str, user: auth.User | None) -> str:
    path = _store_dir(store_id) / name
    if not path.exists() or not auth.can_read(user, store_id):       # 남의 매장은 '없는 매장'과 똑같이 답한다
        raise HTTPException(404, f"{store_id}의 {name}이(가) 없습니다. 먼저 예측을 실행하세요.")
    return path.read_text(encoding="utf-8")


def _read_only():
    if DEMO_MODE:
        raise HTTPException(403, "시연용 화면에서는 파일을 올리거나 예측을 새로 돌리거나 설정을 바꿀 수 없습니다.")


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/config")
def config():
    """화면이 처음에 물어본다: 시연 모드면 '데이터 올리기'와 준비 방식 바꾸기를 숨긴다.
    google_client_id가 있으면 구글 로그인 버튼을, kakao_login이면 카카오 로그인 버튼을 보여 준다
    (클라이언트 ID는 공개돼도 되는 값. 시연 모드는 보기 전용이라 로그인이 없다)."""
    return {"demo_mode": DEMO_MODE, "google_client_id": None if DEMO_MODE else auth.CLIENT_ID,
            "kakao_login": not DEMO_MODE and bool(auth.KAKAO_KEY)}


@app.get("/api/stores")
def stores(user: auth.User | None = Me):
    """내일 예측(forecast.json)이 있는 매장 중 내가 볼 수 있는 것.
    can_edit: 내가 고칠 수 있는지.  demo: 누구나 보는 예시 매장인지 (화면은 로그인 전 첫 화면에만 보여 준다)."""
    out = []
    for folder in sorted(p.parent for p in ARTIFACTS.glob("*/forecast.json")):
        if not auth.can_read(user, folder.name):
            continue
        store = StoreConfig.read(folder / "store.json") if (folder / "store.json").exists() \
            else StoreConfig(store_id=folder.name)
        out.append(dict(store_id=folder.name, name=store.name or folder.name, prep_mode=store.prep_mode,
                        can_edit=not DEMO_MODE and auth.can_write(user, folder.name),
                        demo=DEMO_MODE or folder.name in auth.DEMO_STORES))
    if auth.enabled():                                   # 로그인을 쓰면 내 매장이 먼저, 시연 매장은 뒤에
        out.sort(key=lambda s: s["store_id"] in auth.DEMO_STORES)
    return out


@app.get("/api/stores/{store_id}/forecast", response_model=Forecast)
def forecast(store_id: str, user: auth.User | None = Me):
    return Forecast.model_validate_json(_read(store_id, "forecast.json", user))


@app.get("/api/stores/{store_id}/backtest", response_model=BacktestResult)
def backtest(store_id: str, user: auth.User | None = Me):
    return BacktestResult.model_validate_json(_read(store_id, "backtest.json", user))


@app.get("/api/stores/{store_id}/sources", response_model=SourceReport)
def sources(store_id: str, user: auth.User | None = Me):
    return SourceReport.model_validate_json(_read(store_id, "sources_report.json", user))


# ---------------------------------------------------------------- 로그인

class GoogleLogin(BaseModel):
    credential: str                    # 구글 로그인 버튼이 화면에 준 ID 토큰


STATE_COOKIE = "nm_oauth_state"            # 카카오로 보낼 때 심어 두는 확인용 값 (10분)
KAKAO_CALLBACK = "/api/auth/kakao/callback"  # 카카오 콘솔의 '리다이렉트 URI'에 등록하는 주소의 뒷부분


def _origin(request: Request) -> str:
    """사용자가 연 주소의 앞부분 (예: http://localhost:5173).
    앞단(개발용 화면 서버, 클라우드)을 거쳐 오면 원래 주소를 x-forwarded-* 헤더로 알려 준다."""
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", request.url.netloc)
    return f"{scheme}://{host.split(',')[0].strip()}"


def _set_session(response: Response, request: Request, token: str) -> None:
    """로그인 쿠키를 준다: 자바스크립트가 못 읽고(HttpOnly), 다른 사이트의 요청에는 안 실리고(Lax), https면 https로만."""
    response.set_cookie(auth.COOKIE, token, max_age=auth.SESSION_DAYS * 86400, httponly=True, samesite="lax",
                        secure=_origin(request).startswith("https"))


@app.post("/api/auth/google")
def auth_google(body: GoogleLogin, request: Request, response: Response):
    if not auth.CLIENT_ID:
        raise HTTPException(404, "이 서버는 구글 로그인을 쓰지 않습니다 (.env에 GOOGLE_CLIENT_ID가 없음).")
    user, token = auth.login(body.credential)
    _set_session(response, request, token)
    return user.public()


@app.get("/api/auth/kakao/start")
def auth_kakao_start(request: Request):
    """카카오 로그인 화면으로 보낸다. 돌아왔을 때 우리가 보낸 요청이 맞는지 보려고 무작위 값(state)을 쿠키에 심어 둔다."""
    if not auth.KAKAO_KEY:
        raise HTTPException(404, "이 서버는 카카오 로그인을 쓰지 않습니다 (.env에 KAKAO_LOGIN=1이 없음).")
    state = secrets.token_urlsafe(16)
    go = RedirectResponse(auth.kakao_login_url(_origin(request) + KAKAO_CALLBACK, state))
    go.set_cookie(STATE_COOKIE, state, max_age=600, httponly=True, samesite="lax", secure=_origin(request).startswith("https"))
    return go


@app.get(KAKAO_CALLBACK)
def auth_kakao_callback(request: Request, code: str | None = None, state: str | None = None):
    """카카오가 사용자를 돌려보내는 곳. 성공하면 로그인 쿠키를 주고 첫 화면으로, 실패·취소면 ?login_error=kakao 로."""
    saved = request.cookies.get(STATE_COOKIE)
    back = RedirectResponse("/?login_error=kakao")
    if auth.KAKAO_KEY and code and state and saved and secrets.compare_digest(state, saved):
        try:
            _, token = auth.login_as("kakao", auth.kakao_profile(code, _origin(request) + KAKAO_CALLBACK))
            back = RedirectResponse("/")
            _set_session(back, request, token)
        except Exception as e:                       # 코드 만료, 시크릿 틀림, 카카오 서버 오류 등 → 서버 기록에 이유를 남긴다
            print(f"[카카오 로그인 실패] {type(e).__name__}: {e}", flush=True)
    back.delete_cookie(STATE_COOKIE)
    return back


@app.get("/api/auth/me")
def auth_me(user: auth.User | None = Me):
    return user.public() if user else None


@app.post("/api/auth/logout")
def auth_logout(request: Request, response: Response):
    auth.logout(request.cookies.get(auth.COOKIE))
    response.delete_cookie(auth.COOKIE)
    return {"ok": True}


# ---------------------------------------------------------------- 내 매장 관리

class NewStore(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    close_time: str = DEFAULT_CLOSE_TIME


class StoreName(BaseModel):
    name: str = Field(min_length=1, max_length=40)


def _member(user: auth.User | None) -> auth.User:
    """내 매장 관리는 로그인을 쓰는 서버에서, 로그인한 사람만."""
    if not auth.enabled():
        raise HTTPException(404, "이 서버는 로그인을 쓰지 않습니다.")
    if user is None:
        raise HTTPException(401, "로그인이 필요합니다.")
    return user


def _my_store(store_id: str, created_at: str | None, mine: bool) -> dict:
    """내 매장 목록의 한 줄. 이름·주소·종료 시각은 store.json, 마지막 계산 시각은 forecast.json이 바뀐 때."""
    folder = ARTIFACTS / store_id
    store = StoreConfig.read(folder / "store.json") if (folder / "store.json").exists() else StoreConfig(store_id=store_id)
    fc = folder / "forecast.json"
    updated = dt.datetime.fromtimestamp(fc.stat().st_mtime).isoformat(timespec="seconds") if fc.exists() else None
    return dict(store_id=store_id, name=store.name or store_id, address=store.address, close_time=store.close_time,
                created_at=created_at, updated_at=updated, ready=fc.exists(), running=store_id in RUNNING, mine=mine)


@app.get("/api/my/stores")
def my_stores(user: auth.User | None = Me):
    """내가 만든 매장 (새것부터). 관리자는 남의 매장과 주인 없는 매장(명령줄로 만든 것)도 뒤에 붙여 본다."""
    user = _member(user)
    mine = auth.my_stores(user)
    out = [_my_store(s, created, True) for s, created in sorted(mine.items(), key=lambda x: x[1], reverse=True)]
    if user.is_admin:
        others = sorted(p.name for p in ARTIFACTS.iterdir()
                        if p.is_dir() and p.name not in mine and p.name not in auth.DEMO_STORES and STORE_ID.match(p.name))
        out += [_my_store(s, None, False) for s in others]
    return out


@app.post("/api/my/stores", status_code=201)
def create_my_store(body: NewStore, user: auth.User | None = Me):
    user = _member(user)
    _read_only()
    if not re.match(CLOSE_TIME, body.close_time):
        raise HTTPException(400, "영업 종료 시각은 21:00처럼 적어 주세요.")
    store_id = auth.create_store(user)
    folder = ARTIFACTS / store_id
    folder.mkdir(parents=True, exist_ok=True)
    StoreConfig(store_id=store_id, name=body.name.strip(), close_time=body.close_time).write(folder / "store.json")
    return _my_store(store_id, auth.my_stores(user)[store_id], True)


@app.patch("/api/my/stores/{store_id}")
def rename_my_store(store_id: str, body: StoreName, user: auth.User | None = Me):
    user = _member(user)
    _read_only()
    path = _store_dir(store_id) / "store.json"
    auth.check_write(user, store_id, exists=path.exists())
    store = StoreConfig.read(path) if path.exists() else StoreConfig(store_id=store_id)
    store.name = body.name.strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    store.write(path)
    return _my_store(store_id, auth.my_stores(user).get(store_id), store_id in auth.my_stores(user))


@app.delete("/api/my/stores/{store_id}")
def delete_my_store(store_id: str, user: auth.User | None = Me):
    """매장을 지운다: 결과 폴더(판매 기록 정리본, 주변 정보, 예측)와 올린 POS 파일, 주인 기록. 되돌릴 수 없다."""
    user = _member(user)
    _read_only()
    folder = _store_dir(store_id)
    if store_id in auth.DEMO_STORES:
        raise HTTPException(403, "시연 매장은 지울 수 없습니다.")
    auth.check_write(user, store_id, exists=folder.exists())             # 남의 매장이면 여기서 404
    with LOCK:
        if store_id in RUNNING:
            raise HTTPException(409, "이 매장은 지금 계산 중입니다. 끝난 뒤 다시 시도해 주세요.")
    for path in (folder, UPLOADS / store_id):
        if path.exists():
            shutil.rmtree(path)
    auth.forget_store(store_id)
    return {"ok": True}


# ---------------------------------------------------------------- 실행

def _start(store_id: str, args: list[str]) -> dict:
    """run.py를 별도 프로세스로 시작하고 작업 번호를 돌려준다. 실행 기록은 한 줄씩 JOBS에 쌓인다.
    누가 해도 되는지는 부르는 쪽(아래 세 API)이 먼저 확인한다."""
    _read_only()
    with LOCK:
        if store_id in RUNNING:
            raise HTTPException(409, f"{store_id}는 이미 실행 중입니다. 끝난 뒤 다시 시도하세요.")
        RUNNING.add(store_id)
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = dict(job_id=job_id, store_id=store_id, status="running", log=[], error=None)
    cmd = [sys.executable, str(paths.ROOT / "run.py"), "--store", store_id, "--artifacts", str(ARTIFACTS), *args]

    def work():
        job = JOBS[job_id]
        try:
            proc = subprocess.Popen(cmd, cwd=paths.ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
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


@app.post("/api/stores/{store_id}/run", status_code=202)
def run_store(store_id: str, pos: UploadFile = File(..., description="POS 엑셀·CSV (토스·OKPOS)"),
              close_time: str | None = Form(None, description="영업 종료 시각 HH:MM"),
              address: str | None = Form(None, description="매장 주소 → 주변 정보 자동 수집"),
              user: auth.User | None = Me):
    folder = _store_dir(store_id)
    _read_only()
    auth.check_write(user, store_id, exists=folder.exists(), create=True)     # 새 ID면 올린 사람의 매장이 된다
    suffix = Path(pos.filename or "").suffix.lower()
    if suffix not in POS_SUFFIXES:
        raise HTTPException(400, "POS 파일은 엑셀(.xlsx·.xls) 또는 .csv여야 합니다.")
    if close_time and not re.match(CLOSE_TIME, close_time):
        raise HTTPException(400, "영업 종료 시각은 21:00처럼 적어 주세요.")
    if close_time and (folder / "store.json").exists():                # 이미 있는 매장: 종료 시각이 바뀌었으면 반영
        store = StoreConfig.read(folder / "store.json")
        if store.close_time != close_time:
            store.close_time = close_time
            store.write(folder / "store.json")
    saved = UPLOADS / store_id / f"pos{suffix}"
    saved.parent.mkdir(parents=True, exist_ok=True)
    saved.write_bytes(pos.file.read())
    args = ["--pos", str(saved)]
    if close_time:
        args += ["--close-time", close_time]
    if address and address.strip():
        args += ["--address", address.strip()]
    return _start(store_id, args)


@app.post("/api/stores/{store_id}/demo", status_code=202)
def run_demo(store_id: str = "sinchon-a", user: auth.User | None = Me):
    folder = _store_dir(store_id)
    _read_only()
    auth.check_write(user, store_id, exists=folder.exists())
    args = ["--demo"]
    sample_collection = paths.SAMPLE / store_id / "collection.json"      # 시험용 가상 기사 (AI 주의 안내 시연)
    if sample_collection.exists():
        args += ["--collection", str(sample_collection)]
    return _start(store_id, args)


@app.post("/api/stores/{store_id}/settings", status_code=202)
def settings(store_id: str, prep_mode: str = Form(...), user: auth.User | None = Me):
    _read_only()
    auth.check_write(user, store_id, exists=_store_dir(store_id).exists())
    if prep_mode not in PREP_MODES:
        raise HTTPException(400, f"준비 방식은 {list(PREP_MODES)} 중 하나여야 합니다.")
    path = _store_dir(store_id) / "store.json"
    if not path.exists():
        raise HTTPException(404, f"{store_id}의 store.json이 없습니다. 먼저 예측을 실행하세요.")
    store = StoreConfig.read(path)
    store.prep_mode = prep_mode
    store.write(path)
    return _start(store_id, ["--from-step", "predict"])


@app.get("/api/jobs/{job_id}")
def job(job_id: str, user: auth.User | None = Me):
    if job_id not in JOBS or not auth.can_read(user, JOBS[job_id]["store_id"]):
        raise HTTPException(404, "그런 작업이 없습니다 (서버를 다시 켜면 작업 기록은 사라집니다).")
    return JOBS[job_id]


# 빌드된 화면 (맨 마지막에 둔다: /api/... 가 먼저 처리되고, 나머지 주소는 화면 파일)
if WEB_DIST.exists():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
