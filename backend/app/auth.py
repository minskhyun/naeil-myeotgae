"""로그인(구글)과 매장 접근 권한.

흐름
  1. 화면의 '구글로 로그인' 버튼을 누르면 구글이 화면에 ID 토큰(구글이 서명한 글자열)을 준다
  2. 화면이 그 토큰을 POST /api/auth/google 로 보낸다
  3. 서버가 토큰을 검증한다 (verify_google: 구글 서명, 우리 앱용인지, 만료, 이메일 인증 여부)
  4. 사용자를 DB에 저장하고, 무작위 세션 번호를 쿠키로 준다 (HttpOnly → 화면의 자바스크립트는 읽지 못함)
  5. 이후 요청은 쿠키로 누구인지 안다 (current_user)
  비밀번호는 받지도 저장하지도 않는다. 구글에서 받는 것은 이름·이메일·프로필 사진 주소뿐이다.

저장: SQLite 파일 하나 (data/app.db, 커밋 안 됨)
  users     누구인지 (구글 계정 번호, 이메일, 이름)
  sessions  로그인 상태 (세션 번호는 해시만 저장 → DB가 새도 남의 로그인을 쓸 수 없음)
  stores    매장 주인

권한 (로그인이 켜져 있을 때)
  - 시연 매장(backend/demo_data에 있는 ID): 누구나 본다. 다시 계산은 관리자만
  - 그 밖의 매장: 주인과 관리자만 보고 고친다
  - 아무도 안 쓰는 ID로 처음 파일을 올리면 올린 사람이 주인이 된다
  - 관리자: .env의 ADMIN_EMAILS (쉼표로 구분). 주인 없는 매장(명령줄로 만든 것)도 관리자가 본다
로그인이 꺼져 있을 때 (.env에 GOOGLE_CLIENT_ID가 없음): 예전처럼 혼자 쓰는 노트북용. 모든 매장을 보고 고친다.
"""
import datetime as dt
import hashlib
import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass

from fastapi import HTTPException, Request

from ml import paths
from ml.llm import settings

_cfg = settings()
CLIENT_ID: str | None = _cfg.get("GOOGLE_CLIENT_ID") or None      # 구글 클라우드에서 만든 'OAuth 클라이언트 ID'. 없으면 로그인 꺼짐
ADMIN_EMAILS = {e.strip().lower() for e in _cfg.get("ADMIN_EMAILS", "").split(",") if e.strip()}
DB_PATH = paths.ROOT / "data" / "app.db"
DEMO_STORES = {p.name for p in (paths.ROOT / "backend" / "demo_data").iterdir() if p.is_dir()}   # 누구나 보는 매장
COOKIE = "nm_session"
SESSION_DAYS = 30                     # 로그인 유지 기간

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    google_sub    TEXT UNIQUE NOT NULL,   -- 구글 계정 번호 (이메일이 바뀌어도 그대로)
    email         TEXT NOT NULL,
    name          TEXT NOT NULL,
    picture       TEXT,
    created_at    TEXT NOT NULL,
    last_login_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,          -- 쿠키에 든 세션 번호의 sha256
    user_id    INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stores (
    store_id   TEXT PRIMARY KEY,
    owner_id   INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
"""


@dataclass
class User:
    id: int
    email: str
    name: str
    picture: str | None

    @property
    def is_admin(self) -> bool:
        return self.email.lower() in ADMIN_EMAILS

    def public(self) -> dict:
        """화면에 주는 내 정보."""
        return dict(email=self.email, name=self.name, picture=self.picture, is_admin=self.is_admin)


# ---------------------------------------------------------------- DB

@contextmanager
def _db():
    """요청마다 잠깐 열고 닫는다 (SQLite 연결은 스레드끼리 나눠 쓰지 않는다)."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(SCHEMA)
        yield con
        con.commit()
    finally:
        con.close()


def _now(days: int = 0) -> str:
    """지금(UTC)에서 days일 뒤. 글자로 저장해도 순서가 시간 순서와 같다."""
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=days)).isoformat(timespec="seconds")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _user(row: sqlite3.Row) -> User:
    return User(id=row["id"], email=row["email"], name=row["name"], picture=row["picture"])


# ---------------------------------------------------------------- 로그인·로그아웃

def verify_google(credential: str) -> dict:
    """구글 ID 토큰 → 계정 정보(sub, email, name, picture). 가짜·만료·다른 앱용 토큰이면 ValueError.
    구글의 공개 키로 서명을 확인하므로 처음 한 번은 구글 서버에 다녀온다."""
    from google.auth.transport import requests as google_requests     # 로그인을 쓸 때만 필요 (pip install google-auth)
    from google.oauth2 import id_token
    claims = id_token.verify_oauth2_token(credential, google_requests.Request(), CLIENT_ID, clock_skew_in_seconds=10)
    if not claims.get("email_verified"):
        raise ValueError("이메일 인증이 안 된 구글 계정")
    return claims


def login(credential: str) -> tuple[User, str]:
    """구글 토큰을 확인하고 (사용자, 세션 번호)를 돌려준다. 처음 온 사람은 여기서 가입된다."""
    try:
        claims = verify_google(credential)
    except ValueError:
        raise HTTPException(401, "구글 로그인 확인에 실패했습니다. 다시 로그인해 주세요.")
    except Exception as e:                                           # 구글 서버에 못 닿는 경우 등
        raise HTTPException(503, f"구글 확인 서버에 연결하지 못했습니다 ({type(e).__name__}). 잠시 뒤 다시 시도해 주세요.")
    now, token = _now(), secrets.token_urlsafe(32)
    name = claims.get("name") or claims["email"].split("@")[0]
    with _db() as con:
        con.execute(
            "INSERT INTO users (google_sub, email, name, picture, created_at, last_login_at) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (google_sub) DO UPDATE SET email = excluded.email, name = excluded.name, "
            "picture = excluded.picture, last_login_at = excluded.last_login_at",
            (claims["sub"], claims["email"], name, claims.get("picture"), now, now))
        row = con.execute("SELECT * FROM users WHERE google_sub = ?", (claims["sub"],)).fetchone()
        con.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))             # 만료된 로그인 정리
        con.execute("INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                    (_hash(token), row["id"], now, _now(SESSION_DAYS)))
    return _user(row), token


def logout(token: str | None) -> None:
    if token:
        with _db() as con:
            con.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash(token),))


def current_user(request: Request) -> User | None:
    """요청의 쿠키로 누구인지 찾는다. 로그인 안 했거나 만료됐으면 None. (FastAPI의 Depends로 쓴다)"""
    token = request.cookies.get(COOKIE)
    if not CLIENT_ID or not token:
        return None
    with _db() as con:
        row = con.execute("SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id "
                          "WHERE s.token_hash = ? AND s.expires_at > ?", (_hash(token), _now())).fetchone()
    return _user(row) if row else None


# ---------------------------------------------------------------- 매장 권한

def owner_of(store_id: str) -> int | None:
    with _db() as con:
        row = con.execute("SELECT owner_id FROM stores WHERE store_id = ?", (store_id,)).fetchone()
    return row["owner_id"] if row else None


def can_read(user: User | None, store_id: str) -> bool:
    if not CLIENT_ID or store_id in DEMO_STORES:
        return True
    return user is not None and (user.is_admin or owner_of(store_id) == user.id)


def can_write(user: User | None, store_id: str) -> bool:
    if not CLIENT_ID:
        return True
    return user is not None and (user.is_admin or owner_of(store_id) == user.id)


def check_write(user: User | None, store_id: str, exists: bool, create: bool = False) -> None:
    """고쳐도 되는지 확인하고, 안 되면 이유와 함께 거절한다.
    create=True(파일 올리기)면 아무도 안 쓰는 ID를 올린 사람의 매장으로 등록한다.
    exists: 그 ID의 결과 폴더가 이미 있는지 (주인 없이 폴더만 있는 매장은 관리자만 가져갈 수 있다)."""
    if not CLIENT_ID:
        return
    if user is None:
        raise HTTPException(401, "로그인이 필요합니다.")
    if create and store_id not in DEMO_STORES and (not exists or user.is_admin):
        with _db() as con:                                           # 이미 주인이 있으면 아무 일도 안 일어난다
            con.execute("INSERT OR IGNORE INTO stores (store_id, owner_id, created_at) VALUES (?, ?, ?)",
                        (store_id, user.id, _now()))
    if can_write(user, store_id):
        return
    if store_id in DEMO_STORES:
        raise HTTPException(403, "시연 매장은 바꿀 수 없습니다. 내 매장은 다른 매장 ID로 올려 주세요.")
    if create:
        raise HTTPException(409, "이미 쓰이고 있는 매장 ID입니다. 다른 ID를 골라 주세요.")
    raise HTTPException(404, f"{store_id} 매장이 없습니다.")
