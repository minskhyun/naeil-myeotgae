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
    assert guest.get("/api/config").json() == {"demo_mode": False, "google_client_id": "test-client-id"}
    assert guest.get("/api/auth/me").json() is None
    assert guest.get("/api/stores").json() == [dict(store_id="sinchon-a", name="sinchon-a", prep_mode="균형", can_edit=False)]
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
    assert alice.get("/api/auth/me").json() == dict(email="alice@example.com", name="앨리스", picture=None, is_admin=False)
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
