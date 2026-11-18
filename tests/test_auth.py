"""로그인이 켜졌을 때의 규칙 (구글 서버는 부르지 않는다: 토큰 검증만 가짜로 바꿔 끼움).

시연 매장은 누구나 보고, 내 매장은 나만 보고 고친다. 파일 올리기는 로그인해야 하고, 처음 올린 사람이 주인이 된다.
"""
import shutil
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import auth, main

EXAMPLES = Path(__file__).resolve().parents[1] / "contracts" / "examples"
PEOPLE = {   # 가짜 구글 토큰 → 구글이 알려 줄 계정 정보
    "alice-token": dict(sub="g-1", email="alice@example.com", name="앨리스", picture=None, email_verified=True),
    "bob-token": dict(sub="g-2", email="bob@example.com", name="밥", picture=None, email_verified=True),
    "boss-token": dict(sub="g-3", email="Boss@Example.com", name="관리자", picture=None, email_verified=True),
}
POS = {"pos": ("pos.csv", b"date,menu,qty\n", "text/csv")}


def _make_store(root: Path, store_id: str):
    (root / store_id).mkdir()
    for name in ("forecast.json", "backtest.json", "sources_report.json"):
        shutil.copyfile(EXAMPLES / name, root / store_id / name)
    (root / store_id / "store.json").write_text(f'{{"store_id": "{store_id}"}}', encoding="utf-8")


@pytest.fixture
def site(tmp_path, monkeypatch):
    """로그인이 켜진 서버. sinchon-a = 시연 매장, old-cafe = 주인 없이 폴더만 있는 매장(명령줄로 만든 것)."""
    _make_store(tmp_path, "sinchon-a")
    _make_store(tmp_path, "old-cafe")

    def fake_verify(credential):
        if credential not in PEOPLE:
            raise ValueError("가짜 토큰")
        return PEOPLE[credential]

    monkeypatch.setattr(main, "ARTIFACTS", tmp_path)
    monkeypatch.setattr(main, "UPLOADS", tmp_path / "uploads")
    monkeypatch.setattr(main, "DEMO_MODE", False)
    monkeypatch.setattr(main, "_start", lambda store_id, args: dict(job_id="j1", store_id=store_id, status="running"))
    monkeypatch.setattr(auth, "CLIENT_ID", "test-client-id")
    monkeypatch.setattr(auth, "KAKAO_KEY", None)                 # 카카오는 아래 카카오 테스트에서만 켠다
    monkeypatch.setattr(auth, "KAKAO_SECRET", None)
    monkeypatch.setattr(auth, "ADMIN_EMAILS", {"boss@example.com"})
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "app.db")
    monkeypatch.setattr(auth, "verify_google", fake_verify)
    return tmp_path


def _login(who: str) -> TestClient:
    client = TestClient(main.app)                       # 사람마다 브라우저(쿠키 통)가 따로
    assert client.post("/api/auth/google", json={"credential": f"{who}-token"}).status_code == 200
    return client


def test_logged_out_sees_only_demo_and_cannot_change(site):
    guest = TestClient(main.app)
    assert guest.get("/api/config").json() == {"demo_mode": False, "google_client_id": "test-client-id", "kakao_login": False}
    assert guest.get("/api/auth/me").json() is None
    assert guest.get("/api/stores").json() == [dict(store_id="sinchon-a", name="sinchon-a", prep_mode="균형", can_edit=False, demo=True)]
    assert guest.get("/api/stores/sinchon-a/forecast").status_code == 200
    assert guest.get("/api/stores/old-cafe/forecast").status_code == 404           # 있는지조차 알려 주지 않는다
    assert guest.post("/api/stores/my-cafe/run", files=POS).status_code == 401
    assert guest.post("/api/stores/sinchon-a/settings", data={"prep_mode": "균형"}).status_code == 401
    assert guest.post("/api/stores/sinchon-a/demo").status_code == 401


def test_bad_google_token_is_rejected(site, monkeypatch):
    guest = TestClient(main.app)
    assert guest.post("/api/auth/google", json={"credential": "made-up"}).status_code == 401
    assert guest.get("/api/auth/me").json() is None

    def google_down(credential):
        raise ConnectionError
    monkeypatch.setattr(auth, "verify_google", google_down)
    assert guest.post("/api/auth/google", json={"credential": "alice-token"}).status_code == 503


def test_unverified_email_is_rejected(monkeypatch):
    """verify_google 자체의 규칙: 구글 서명이 맞아도 이메일 인증이 안 된 계정은 받지 않는다."""
    from google.oauth2 import id_token
    monkeypatch.setattr(auth, "CLIENT_ID", "test-client-id")
    monkeypatch.setattr(id_token, "verify_oauth2_token", lambda *a, **k: dict(sub="g-9", email="x@example.com", email_verified=False))
    with pytest.raises(ValueError):
        auth.verify_google("any")


def test_first_uploader_owns_the_store(site):
    alice, bob = _login("alice"), _login("bob")
    assert alice.get("/api/auth/me").json() == dict(provider="google", email="alice@example.com", name="앨리스", picture=None,
                                                    is_admin=False)
    assert alice.post("/api/stores/alice-cafe/run", files=POS).status_code == 202      # 새 ID → 앨리스의 매장
    _make_store(site, "alice-cafe")                                                    # (실행이 끝나 결과가 생겼다고 치고)

    assert {s["store_id"]: s["can_edit"] for s in alice.get("/api/stores").json()} == {"alice-cafe": True, "sinchon-a": False}
    assert alice.get("/api/stores/alice-cafe/forecast").status_code == 200
    assert alice.post("/api/stores/alice-cafe/settings", data={"prep_mode": "균형"}).status_code == 202
    assert alice.post("/api/stores/alice-cafe/run", files=POS).status_code == 202      # 내 매장은 다시 올려도 된다

    assert [s["store_id"] for s in bob.get("/api/stores").json()] == ["sinchon-a"]
    assert bob.get("/api/stores/alice-cafe/forecast").status_code == 404
    assert bob.post("/api/stores/alice-cafe/run", files=POS).status_code == 409        # 이미 쓰이는 ID
    assert bob.post("/api/stores/alice-cafe/settings", data={"prep_mode": "균형"}).status_code == 404

    main.JOBS["job-a"] = dict(job_id="job-a", store_id="alice-cafe", status="running", log=[], error=None)
    try:
        assert alice.get("/api/jobs/job-a").status_code == 200
        assert bob.get("/api/jobs/job-a").status_code == 404                           # 남의 실행 기록도 못 본다
    finally:
        del main.JOBS["job-a"]


def test_demo_and_ownerless_stores_are_for_admin_only(site):
    alice, boss = _login("alice"), _login("boss")
    assert alice.post("/api/stores/sinchon-a/demo").status_code == 403                 # 시연 매장은 못 바꾼다
    assert alice.post("/api/stores/sinchon-a/run", files=POS).status_code == 403
    assert alice.post("/api/stores/old-cafe/run", files=POS).status_code == 409        # 주인 없는 폴더를 가로챌 수 없다

    assert boss.get("/api/auth/me").json()["is_admin"] is True                         # 이메일 대소문자는 무시
    assert [s["store_id"] for s in boss.get("/api/stores").json()] == ["old-cafe", "sinchon-a"]
    assert boss.post("/api/stores/sinchon-a/demo").status_code == 202
    assert boss.post("/api/stores/old-cafe/settings", data={"prep_mode": "균형"}).status_code == 202


def test_logout_and_expiry_end_the_session(site):
    alice = _login("alice")
    cookie = alice.cookies.get(auth.COOKIE)
    assert alice.post("/api/auth/logout").json() == {"ok": True}
    assert alice.get("/api/auth/me").json() is None
    thief = TestClient(main.app, cookies={auth.COOKIE: cookie})                        # 훔친 옛 쿠키도 못 쓴다
    assert thief.get("/api/auth/me").json() is None

    alice = _login("alice")
    con = sqlite3.connect(auth.DB_PATH)
    assert con.execute("SELECT count(*) FROM users").fetchone()[0] == 1                # 다시 로그인해도 사용자는 한 명
    assert alice.cookies.get(auth.COOKIE) not in [r[0] for r in con.execute("SELECT token_hash FROM sessions")]   # 해시만 저장
    con.execute("UPDATE sessions SET expires_at = '2000-01-01T00:00:00+00:00'")
    con.commit()
    con.close()
    assert alice.get("/api/auth/me").json() is None                                    # 만료된 로그인


def test_login_off_keeps_single_user_behavior(site, monkeypatch):
    """GOOGLE_CLIENT_ID가 없으면 예전처럼: 로그인 없이 모든 매장을 보고 고친다."""
    monkeypatch.setattr(auth, "CLIENT_ID", None)
    solo = TestClient(main.app)
    assert solo.get("/api/config").json()["google_client_id"] is None
    assert {s["store_id"]: s["can_edit"] for s in solo.get("/api/stores").json()} == {"old-cafe": True, "sinchon-a": True}
    assert solo.post("/api/stores/new-cafe/run", files=POS).status_code == 202
    assert solo.post("/api/auth/google", json={"credential": "alice-token"}).status_code == 404


# ---------------------------------------------------------------- 내 매장 관리 (/api/my/stores)

def test_my_stores_create_rename_upload_delete(site):
    alice, bob = _login("alice"), _login("bob")
    assert alice.get("/api/my/stores").json() == []
    made = alice.post("/api/my/stores", json={"name": " 앨리스 빵집 ", "close_time": "20:30"}).json()
    sid = made["store_id"]
    assert sid.startswith("s-") and made["name"] == "앨리스 빵집" and made["close_time"] == "20:30"
    assert (made["ready"], made["running"], made["mine"], made["updated_at"]) == (False, False, True, None)
    assert [s["store_id"] for s in alice.get("/api/stores").json()] == ["sinchon-a"]   # 준비표가 아직 없으면 매장 고르기에는 안 나옴

    assert alice.post(f"/api/stores/{sid}/run", files=POS, data={"close_time": "19:00"}).status_code == 202
    assert alice.get("/api/my/stores").json()[0]["close_time"] == "19:00"              # 다시 올리며 바꾼 종료 시각이 반영됨
    assert alice.post(f"/api/stores/{sid}/run", files=POS, data={"close_time": "9시"}).status_code == 400
    assert (site / "uploads" / sid / "pos.csv").exists()

    assert alice.patch(f"/api/my/stores/{sid}", json={"name": "앨리스 베이커리"}).json()["name"] == "앨리스 베이커리"
    assert alice.patch(f"/api/my/stores/{sid}", json={"name": ""}).status_code == 422

    assert bob.get("/api/my/stores").json() == []                                      # 남의 매장은 안 보이고
    assert bob.patch(f"/api/my/stores/{sid}", json={"name": "밥의 것"}).status_code == 404
    assert bob.delete(f"/api/my/stores/{sid}").status_code == 404                      # 지울 수도 없다
    assert (site / sid / "store.json").exists()

    main.RUNNING.add(sid)
    try:
        assert alice.delete(f"/api/my/stores/{sid}").status_code == 409                # 계산 중에는 못 지운다
    finally:
        main.RUNNING.discard(sid)
    assert alice.delete(f"/api/my/stores/{sid}").json() == {"ok": True}
    assert not (site / sid).exists() and not (site / "uploads" / sid).exists()         # 결과와 올린 파일이 모두 사라짐
    assert alice.get("/api/my/stores").json() == [] and auth.owner_of(sid) is None


def test_my_stores_rules(site, monkeypatch):
    guest, alice, boss = TestClient(main.app), _login("alice"), _login("boss")
    assert guest.get("/api/my/stores").status_code == 401
    assert guest.post("/api/my/stores", json={"name": "가게"}).status_code == 401
    assert alice.delete("/api/my/stores/sinchon-a").status_code == 403                 # 시연 매장은 누구도 못 지운다
    assert boss.delete("/api/my/stores/sinchon-a").status_code == 403
    assert alice.delete("/api/my/stores/old-cafe").status_code == 404                  # 주인 없는 매장은 관리자만
    assert alice.post("/api/my/stores", json={"name": "가게", "close_time": "25:00"}).status_code == 400

    monkeypatch.setattr(auth, "MAX_STORES", 2)
    for i in range(2):
        assert alice.post("/api/my/stores", json={"name": f"가게 {i}"}).status_code == 201
    assert alice.post("/api/my/stores", json={"name": "하나 더"}).status_code == 409    # 한 사람당 매장 수 제한

    listed = {s["store_id"]: s["mine"] for s in boss.get("/api/my/stores").json()}     # 관리자는 남의 매장·주인 없는 매장도 본다
    assert listed["old-cafe"] is False and len(listed) == 3 and "sinchon-a" not in listed
    assert boss.delete("/api/my/stores/old-cafe").json() == {"ok": True} and not (site / "old-cafe").exists()

    monkeypatch.setattr(auth, "CLIENT_ID", None)                                       # 로그인을 안 쓰는 서버에는 이 기능이 없다
    assert guest.get("/api/my/stores").status_code == 404


# ---------------------------------------------------------------- 카카오 로그인

@pytest.fixture
def kakao(site, monkeypatch):
    """카카오 로그인이 켜진 서버. 카카오 서버 대신 가짜 kakao_profile: 인가 코드 → 계정 정보."""
    people = {"code-min": dict(sub="k-1", email=None, name="민지", picture=None),               # 이메일 제공에 동의 안 함
              "code-alice": dict(sub="k-2", email="alice@example.com", name="앨리스(카카오)", picture=None)}
    seen = {}

    def fake_profile(code, redirect_uri):
        seen["redirect_uri"] = redirect_uri
        if code not in people:
            raise ValueError("카카오 토큰 요청 실패 400 KOE320")
        return people[code]

    monkeypatch.setattr(auth, "KAKAO_KEY", "kakao-rest-key")
    monkeypatch.setattr(auth, "kakao_profile", fake_profile)
    return seen


def _kakao_login(code: str) -> tuple[TestClient, str]:
    """카카오 버튼을 누른 뒤의 흐름: start(카카오로 보냄) → 카카오가 code와 state를 붙여 callback으로 돌려보냄.
    돌려주는 값: (그 사람의 브라우저, 마지막에 보내진 주소)"""
    client = TestClient(main.app, follow_redirects=False)
    go = client.get("/api/auth/kakao/start")
    assert go.status_code == 307 and go.headers["location"].startswith("https://kauth.kakao.com/oauth/authorize?client_id=kakao-rest-key")
    state = client.cookies.get(main.STATE_COOKIE)
    assert f"state={state}" in go.headers["location"] and "response_type=code" in go.headers["location"]
    back = client.get(f"/api/auth/kakao/callback?code={code}&state={state}")
    assert back.status_code == 307
    return client, back.headers["location"]


def test_kakao_login_flow(kakao):
    assert TestClient(main.app).get("/api/config").json()["kakao_login"] is True
    minji, landed = _kakao_login("code-min")
    assert landed == "/" and kakao["redirect_uri"] == "http://testserver/api/auth/kakao/callback"
    assert minji.get("/api/auth/me").json() == dict(provider="kakao", email=None, name="민지", picture=None, is_admin=False)
    assert not minji.cookies.get(main.STATE_COOKIE)                                    # 확인용 값은 한 번 쓰고 지운다
    made = minji.post("/api/my/stores", json={"name": "민지네"})                        # 이메일이 없어도 매장을 만들 수 있다
    assert made.status_code == 201 and [s["name"] for s in minji.get("/api/my/stores").json()] == ["민지네"]


def test_kakao_and_google_are_separate_accounts(kakao):
    """이메일이 같아도 합치지 않는다: 카카오 쪽 계정이 구글 쪽 계정의 매장을 볼 수 없다."""
    google_alice, (kakao_alice, _) = _login("alice"), _kakao_login("code-alice")
    sid = google_alice.post("/api/my/stores", json={"name": "구글 앨리스의 가게"}).json()["store_id"]
    assert kakao_alice.get("/api/auth/me").json()["email"] == "alice@example.com"
    assert kakao_alice.get("/api/my/stores").json() == []
    assert kakao_alice.delete(f"/api/my/stores/{sid}").status_code == 404
    con = sqlite3.connect(auth.DB_PATH)
    assert sorted(con.execute("SELECT provider, subject FROM users").fetchall()) == [("google", "g-1"), ("kakao", "k-2")]
    con.close()


def test_kakao_callback_rejects_bad_requests(kakao, monkeypatch):
    client = TestClient(main.app, follow_redirects=False)
    client.get("/api/auth/kakao/start")
    state = client.cookies.get(main.STATE_COOKIE)
    for url in ("/api/auth/kakao/callback?code=code-min&state=someone-elses",         # 우리가 보낸 요청이 아님
                f"/api/auth/kakao/callback?error=access_denied&state={state}",        # 사용자가 취소
                f"/api/auth/kakao/callback?code=expired&state={state}"):              # 카카오가 코드를 거절
        client.cookies.set(main.STATE_COOKIE, state)
        assert client.get(url).headers["location"] == "/?login_error=kakao"
        assert client.get("/api/auth/me").json() is None
    fresh = TestClient(main.app, follow_redirects=False)                               # state 쿠키 없이 바로 온 요청
    assert fresh.get("/api/auth/kakao/callback?code=code-min&state=x").headers["location"] == "/?login_error=kakao"

    monkeypatch.setattr(auth, "KAKAO_KEY", None)                                       # 카카오 로그인을 안 쓰는 서버
    assert client.get("/api/auth/kakao/start").status_code == 404


def test_kakao_profile_reads_only_verified_email(monkeypatch):
    """kakao_profile 자체의 규칙: 코드 → 토큰 → 사용자 정보. 인증 안 된 이메일은 버리고, 시크릿이 있으면 함께 보낸다."""
    import requests
    sent = {"verified": True}

    class Reply:
        def __init__(self, status, body):
            self.status_code, self._body = status, body

        def json(self):
            return self._body

    def fake_post(url, data, timeout):
        sent.update(url=url, **data)
        return Reply(200, {"access_token": "tok"}) if data["code"] == "good" else Reply(400, {"error_code": "KOE320"})

    def fake_get(url, headers, params, timeout):
        sent["auth"] = headers["Authorization"]
        account = {"email": "a@example.com", "is_email_valid": True, "is_email_verified": sent["verified"],
                   "profile": {"nickname": "민지", "profile_image_url": "https://img/1.jpg"}}
        return Reply(200, {"id": 4242, "kakao_account": account})

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(auth, "KAKAO_KEY", "kakao-rest-key")
    monkeypatch.setattr(auth, "KAKAO_SECRET", "s3cret")
    assert auth.kakao_profile("good", "http://x/cb") == dict(sub="4242", email="a@example.com", name="민지", picture="https://img/1.jpg")
    assert (sent["url"], sent["client_id"], sent["client_secret"], sent["redirect_uri"], sent["grant_type"], sent["auth"]) == \
        (auth.KAKAO_TOKEN, "kakao-rest-key", "s3cret", "http://x/cb", "authorization_code", "Bearer tok")
    sent["verified"] = False
    assert auth.kakao_profile("good", "http://x/cb")["email"] is None
    with pytest.raises(ValueError, match="KOE320"):
        auth.kakao_profile("used-twice", "http://x/cb")


def test_old_google_only_database_is_migrated(site):
    """구글 로그인만 있던 때의 DB(users.google_sub)가 있어도, 사용자 번호·로그인 상태·매장 주인이 그대로 이어진다."""
    con = sqlite3.connect(auth.DB_PATH)
    con.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY, google_sub TEXT UNIQUE NOT NULL, email TEXT NOT NULL, name TEXT NOT NULL,
                            picture TEXT, created_at TEXT NOT NULL, last_login_at TEXT NOT NULL);
        CREATE TABLE sessions (token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL);
        CREATE TABLE stores (store_id TEXT PRIMARY KEY, owner_id INTEGER NOT NULL, created_at TEXT NOT NULL);
        INSERT INTO users VALUES (7, 'g-1', 'alice@example.com', '앨리스', NULL, '2026-11-18T00:00:00+00:00', '2026-11-18T00:00:00+00:00');
        INSERT INTO stores VALUES ('old-cafe', 7, '2026-11-18T00:00:00+00:00');
    """)
    con.execute("INSERT INTO sessions VALUES (?, 7, '2026-11-18T00:00:00+00:00', '2999-01-01T00:00:00+00:00')", (auth._hash("old-cookie"),))
    con.commit()
    con.close()

    alice = TestClient(main.app, cookies={auth.COOKIE: "old-cookie"})                  # 예전에 받은 쿠키 그대로
    assert alice.get("/api/auth/me").json()["provider"] == "google"
    assert [s["store_id"] for s in alice.get("/api/my/stores").json()] == ["old-cafe"]
    assert _login("alice").get("/api/my/stores").json()[0]["store_id"] == "old-cafe"   # 다시 로그인해도 같은 사람(번호 7)
    con = sqlite3.connect(auth.DB_PATH)
    assert con.execute("SELECT id, provider, subject FROM users").fetchall() == [(7, "google", "g-1")]
    con.close()
