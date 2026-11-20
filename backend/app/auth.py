"""로그인(구글·카카오)과 매장 접근 권한.

흐름 (어느 쪽이든 끝은 같다: 사용자를 DB에 저장하고 세션 쿠키를 준다)
  구글   화면의 구글 버튼이 구글에서 ID 토큰을 받아 POST /api/auth/google 로 보낸다
         → verify_google: 구글 서명, 우리 앱용인지, 만료, 이메일 인증 여부를 확인
  카카오 화면의 카카오 버튼이 GET /api/auth/kakao/start 로 간다 → 카카오 로그인 화면
         → 카카오가 '인가 코드'를 붙여 /api/auth/kakao/callback 으로 돌려보낸다
         → kakao_profile: 코드를 토큰으로 바꾸고 그 토큰으로 사용자 정보를 받는다
  → login_as(provider, 계정 정보): 사용자를 저장하고 무작위 세션 번호를 만든다 (쿠키는 HttpOnly → 화면의 자바스크립트는 못 읽음)
  → 이후 요청은 쿠키로 누구인지 안다 (current_user)
  비밀번호는 받지도 저장하지도 않는다. 받는 것은 이름(닉네임)·이메일·프로필 사진 주소뿐이다.
  같은 사람이 구글과 카카오로 각각 로그인하면 서로 다른 계정이다.
  (이메일이 같다고 합치면, 남의 이메일을 쓰는 계정으로 그 사람의 매장을 볼 수 있게 되므로 합치지 않는다)

저장: SQLite 파일 하나 (data/app.db, 커밋 안 됨)
  users     누구인지 (어느 로그인인지, 그 서비스의 계정 번호, 이메일, 이름)
  sessions  로그인 상태 (세션 번호는 해시만 저장 → DB가 새도 남의 로그인을 쓸 수 없음)
  stores    매장 주인
  처음 로그인하면 화면이 이용약관 · 개인정보 수집·이용 동의를 한 번 묻는다 (users.agreed_at). 동의 전에는 매장을 만들거나 고칠 수 없다.
  탈퇴(delete_user)하면 계정과 로그인 상태, 매장 주인 기록을 지운다 (매장 자료는 main.delete_me가 지운다).

권한 (로그인이 켜져 있을 때)
  - 시연 매장(backend/demo_data에 있는 ID): 누구나 본다. 다시 계산은 관리자만
  - 그 밖의 매장: 주인과 관리자만 보고 고친다
  - 매장은 '매장 추가'에서 만든다: 서버가 매장 ID를 지어 주고(create_store) 만든 사람이 주인이 된다
    (API로 아무도 안 쓰는 ID에 직접 올려도 올린 사람이 주인이 된다)
  - 관리자: .env의 ADMIN_EMAILS (쉼표로 구분). 주인 없는 매장(명령줄로 만든 것)도 관리자가 본다
로그인이 꺼져 있을 때 (.env에 GOOGLE_CLIENT_ID도 KAKAO_LOGIN=1도 없음): 예전처럼 혼자 쓰는 노트북용. 모든 매장을 보고 고친다.
"""
import datetime as dt
import hashlib
import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from urllib.parse import urlencode

from fastapi import HTTPException, Request

from ml import paths
from ml.llm import settings

_cfg = settings()
CLIENT_ID: str | None = _cfg.get("GOOGLE_CLIENT_ID") or None      # 구글 클라우드에서 만든 'OAuth 클라이언트 ID'. 없으면 구글 로그인 꺼짐
# 카카오 로그인: KAKAO_LOGIN=1 일 때만 켠다 (REST API 키는 지도 검색에도 쓰므로, 키가 있다고 로그인까지 켜지지는 않게)
KAKAO_KEY: str | None = (_cfg.get("KAKAO_REST_KEY") or None) if _cfg.get("KAKAO_LOGIN") == "1" else None
KAKAO_SECRET: str | None = _cfg.get("KAKAO_CLIENT_SECRET") or None   # 카카오 콘솔에서 '클라이언트 시크릿'이 켜져 있으면 필요 (기본이 켜짐)
ADMIN_EMAILS = {e.strip().lower() for e in _cfg.get("ADMIN_EMAILS", "").split(",") if e.strip()}
DB_PATH = paths.ROOT / "data" / "app.db"
DEMO_STORES = {p.name for p in (paths.ROOT / "backend" / "demo_data").iterdir() if p.is_dir()}   # 누구나 보는 매장
COOKIE = "nm_session"
SESSION_DAYS = 30                     # 로그인 유지 기간
MAX_STORES = 10                       # 한 사람이 만들 수 있는 매장 수 (관리자는 제한 없음)
KAKAO_AUTHORIZE = "https://kauth.kakao.com/oauth/authorize"
KAKAO_TOKEN = "https://kauth.kakao.com/oauth/token"
KAKAO_ME = "https://kapi.kakao.com/v2/user/me"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    provider      TEXT NOT NULL,          -- 어느 로그인인지: 'google' | 'kakao'
    subject       TEXT NOT NULL,          -- 그 서비스의 계정 번호 (이메일이 바뀌어도 그대로)
    email         TEXT,                   -- 인증된 이메일만. 카카오는 이메일 제공에 동의하지 않았으면 비어 있다
    name          TEXT NOT NULL,
    picture       TEXT,
    created_at    TEXT NOT NULL,
    last_login_at TEXT NOT NULL,
    agreed_at     TEXT,                   -- 이용약관 · 개인정보 수집·이용에 동의한 시각 (비어 있으면 아직 동의하지 않음)
    UNIQUE (provider, subject)
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


def enabled() -> bool:
    """로그인을 쓰는 서버인가 (구글·카카오 중 하나라도 설정돼 있으면)."""
    return bool(CLIENT_ID or KAKAO_KEY)


@dataclass
class User:
    id: int
    provider: str
    email: str | None
    name: str
    picture: str | None
    agreed: bool = False            # 이용약관 · 개인정보 수집·이용에 동의했는가 (동의 전에는 매장을 만들거나 고칠 수 없다)

    @property
    def is_admin(self) -> bool:
        return bool(self.email) and self.email.lower() in ADMIN_EMAILS

    def public(self) -> dict:
        """화면에 주는 내 정보."""
        return dict(provider=self.provider, email=self.email, name=self.name, picture=self.picture, is_admin=self.is_admin,
                    agreed=self.agreed)


# ---------------------------------------------------------------- DB

def _prepare(con: sqlite3.Connection) -> None:
    """표가 없으면 만든다. 구글 로그인만 있던 때의 DB(users.google_sub)는 지금 형식으로 옮긴다.
    사용자 번호(id)는 그대로라서 로그인 상태와 매장 주인이 유지된다."""
    old = "google_sub" in {row[1] for row in con.execute("PRAGMA table_info(users)")}
    if old:
        con.execute("ALTER TABLE users RENAME TO users_old")
    con.executescript(SCHEMA)
    if "agreed_at" not in {row[1] for row in con.execute("PRAGMA table_info(users)")}:    # 동의 칸이 생기기 전의 DB
        con.execute("ALTER TABLE users ADD COLUMN agreed_at TEXT")
    if old:
        con.executescript(
            "INSERT INTO users (id, provider, subject, email, name, picture, created_at, last_login_at) "
            "SELECT id, 'google', google_sub, email, name, picture, created_at, last_login_at FROM users_old; "
            "DROP TABLE users_old;")


@contextmanager
def _db():
    """요청마다 잠깐 열고 닫는다 (SQLite 연결은 스레드끼리 나눠 쓰지 않는다)."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        _prepare(con)
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
    return User(id=row["id"], provider=row["provider"], email=row["email"], name=row["name"], picture=row["picture"],
                agreed=bool(row["agreed_at"]))


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


def kakao_login_url(redirect_uri: str, state: str, scope: str | None = None) -> str:
    """카카오 로그인 화면 주소. state는 우리가 보낸 요청이 맞는지 돌아왔을 때 확인하는 무작위 값.
    scope를 주면 그 동의항목만 따로 물어보는 화면이 된다 (이미 가입한 사람에게 닉네임 제공 동의를 받을 때)."""
    query = dict(client_id=KAKAO_KEY, redirect_uri=redirect_uri, response_type="code", state=state)
    if scope:
        query["scope"] = scope
    return KAKAO_AUTHORIZE + "?" + urlencode(query)


def kakao_profile(code: str, redirect_uri: str) -> dict:
    """카카오가 준 인가 코드 → 계정 정보(sub, email, name, picture, ask_nickname). 실패하면 ValueError.
    코드 → 액세스 토큰(서버끼리) → 사용자 정보. 토큰은 여기서만 쓰고 저장하지 않는다.
    name은 카카오 닉네임(프로필 이름). 닉네임을 못 받으면 "카카오 사용자".
    ask_nickname: 닉네임 동의항목은 켜져 있는데 이 사람이 아직 동의하지 않았다 → 한 번 더 물어보면 받을 수 있다."""
    import requests
    body = dict(grant_type="authorization_code", client_id=KAKAO_KEY, redirect_uri=redirect_uri, code=code)
    if KAKAO_SECRET:
        body["client_secret"] = KAKAO_SECRET
    got = requests.post(KAKAO_TOKEN, data=body, timeout=10)
    if got.status_code != 200:                                       # 예: KOE320(코드 만료·재사용), KOE010(시크릿 틀림)
        raise ValueError(f"카카오 토큰 요청 실패 {got.status_code} {got.json().get('error_code', '')}")
    me = requests.get(KAKAO_ME, headers={"Authorization": f"Bearer {got.json()['access_token']}"},
                      params={"secure_resource": "true"}, timeout=10)
    if me.status_code != 200:
        raise ValueError(f"카카오 사용자 정보 요청 실패 {me.status_code}")
    data = me.json()
    account = data.get("kakao_account") or {}
    profile = account.get("profile") or {}
    verified = account.get("is_email_valid") and account.get("is_email_verified")    # 인증된 이메일만 믿는다
    nickname = profile.get("nickname")
    return dict(sub=str(data["id"]), email=account.get("email") if verified else None,
                name=nickname or "카카오 사용자", picture=profile.get("profile_image_url"),
                ask_nickname=not nickname and account.get("profile_nickname_needs_agreement") is True)


def login_as(provider: str, profile: dict) -> tuple[User, str]:
    """확인이 끝난 계정 정보(sub, email, name, picture)로 로그인시킨다 → (사용자, 세션 번호).
    처음 온 사람은 여기서 가입된다."""
    now, token = _now(), secrets.token_urlsafe(32)
    email = profile.get("email")
    name = profile.get("name") or (email.split("@")[0] if email else "사용자")
    with _db() as con:
        con.execute(
            "INSERT INTO users (provider, subject, email, name, picture, created_at, last_login_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (provider, subject) DO UPDATE SET email = excluded.email, name = excluded.name, "
            "picture = excluded.picture, last_login_at = excluded.last_login_at",
            (provider, profile["sub"], email, name, profile.get("picture"), now, now))
        row = con.execute("SELECT * FROM users WHERE provider = ? AND subject = ?", (provider, profile["sub"])).fetchone()
        con.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))             # 만료된 로그인 정리
        con.execute("INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                    (_hash(token), row["id"], now, _now(SESSION_DAYS)))
    return _user(row), token


def login(credential: str) -> tuple[User, str]:
    """구글 토큰을 확인하고 로그인시킨다."""
    try:
        claims = verify_google(credential)
    except ValueError:
        raise HTTPException(401, "구글 로그인 확인에 실패했습니다. 다시 로그인해 주세요.")
    except Exception as e:                                           # 구글 서버에 못 닿는 경우 등
        raise HTTPException(503, f"구글 확인 서버에 연결하지 못했습니다 ({type(e).__name__}). 잠시 뒤 다시 시도해 주세요.")
    return login_as("google", claims)


def logout(token: str | None) -> None:
    if token:
        with _db() as con:
            con.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash(token),))


def agree(user: User) -> User:
    """이용약관 · 개인정보 수집·이용 동의를 기록한다 (처음 로그인했을 때 화면이 한 번 묻는다)."""
    with _db() as con:
        con.execute("UPDATE users SET agreed_at = COALESCE(agreed_at, ?) WHERE id = ?", (_now(), user.id))
        row = con.execute("SELECT * FROM users WHERE id = ?", (user.id,)).fetchone()
    return _user(row)


def check_agreed(user: User | None) -> None:
    """동의하지 않은 사람은 매장을 만들거나 고치지 못한다 (로그인을 안 쓰는 서버에는 해당 없음)."""
    if enabled() and user is not None and not user.agreed:
        raise HTTPException(403, "이용약관과 개인정보 수집·이용에 동의한 뒤 쓸 수 있습니다.")


def delete_user(user: User) -> None:
    """탈퇴: 계정, 로그인 상태, 매장 주인 기록을 지운다. 매장 자료(폴더)는 부르는 쪽이 먼저 지운다 (main.delete_me)."""
    with _db() as con:
        con.execute("DELETE FROM sessions WHERE user_id = ?", (user.id,))
        con.execute("DELETE FROM stores WHERE owner_id = ?", (user.id,))
        con.execute("DELETE FROM users WHERE id = ?", (user.id,))


def current_user(request: Request) -> User | None:
    """요청의 쿠키로 누구인지 찾는다. 로그인 안 했거나 만료됐으면 None. (FastAPI의 Depends로 쓴다)"""
    token = request.cookies.get(COOKIE)
    if not enabled() or not token:
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


def my_stores(user: User) -> dict[str, str]:
    """내가 주인인 매장: {매장 ID: 만든 시각}."""
    with _db() as con:
        rows = con.execute("SELECT store_id, created_at FROM stores WHERE owner_id = ?", (user.id,)).fetchall()
    return {r["store_id"]: r["created_at"] for r in rows}


def create_store(user: User) -> str:
    """새 매장 ID를 지어 내 매장으로 등록한다 (예: s-9f3a1c2e). 이름·주소는 store.json에 둔다."""
    if not user.is_admin and len(my_stores(user)) >= MAX_STORES:
        raise HTTPException(409, f"매장은 {MAX_STORES}개까지 만들 수 있습니다. 안 쓰는 매장을 지운 뒤 다시 시도해 주세요.")
    store_id = "s-" + secrets.token_hex(4)
    with _db() as con:
        con.execute("INSERT INTO stores (store_id, owner_id, created_at) VALUES (?, ?, ?)", (store_id, user.id, _now()))
    return store_id


def forget_store(store_id: str) -> None:
    """매장 주인 기록을 지운다 (매장 자료를 지운 뒤에 부른다)."""
    with _db() as con:
        con.execute("DELETE FROM stores WHERE store_id = ?", (store_id,))


def can_read(user: User | None, store_id: str) -> bool:
    if not enabled() or store_id in DEMO_STORES:
        return True
    return user is not None and (user.is_admin or owner_of(store_id) == user.id)


def can_write(user: User | None, store_id: str) -> bool:
    if not enabled():
        return True
    return user is not None and (user.is_admin or owner_of(store_id) == user.id)


def check_write(user: User | None, store_id: str, exists: bool, create: bool = False) -> None:
    """고쳐도 되는지 확인하고, 안 되면 이유와 함께 거절한다.
    create=True(파일 올리기)면 아무도 안 쓰는 ID를 올린 사람의 매장으로 등록한다.
    exists: 그 ID의 결과 폴더가 이미 있는지 (주인 없이 폴더만 있는 매장은 관리자만 가져갈 수 있다)."""
    if not enabled():
        return
    if user is None:
        raise HTTPException(401, "로그인이 필요합니다.")
    check_agreed(user)
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
