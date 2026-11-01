"""Rate limits, login lockout, response headers and production start-up checks."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from compliance_copilot import security
from compliance_copilot.config import get_settings
from compliance_copilot.db import engine
from compliance_copilot.ratelimit import RateLimiter


def test_sliding_window_allows_then_blocks_then_recovers():
    rl = RateLimiter()
    assert [rl.hit("k", 3, 60, now=t)[0] for t in (0, 1, 2)] == [0, 0, 0]
    retry, first = rl.hit("k", 3, 60, now=3)
    assert retry == pytest.approx(57) and first
    assert rl.hit("k", 3, 60, now=4) == (pytest.approx(56), False)  # only the first violation is flagged
    assert rl.hit("other", 3, 60, now=4)[0] == 0  # keys are independent
    assert rl.hit("k", 3, 60, now=61)[0] == 0  # window slid past the first hit


@pytest.fixture
def client(corpus):
    from compliance_copilot.api.main import app
    from compliance_copilot.security import seed_users

    seed_users()
    with TestClient(app) as c:
        yield c


def _login(client, user, pw):
    return client.post("/auth/login", json={"username": user, "password": pw})


@pytest.fixture
def temp_user(corpus):
    """A throw-away account so lockout tests never lock a demo user."""
    from compliance_copilot.db import User, init_db, session

    init_db()
    with session() as db:
        db.add(User(username="zz-lock-test", display_name="t", role="employee", department="retail",
                    clearance=1, password_hash=security.hash_password("right-password")))
    yield "zz-lock-test"
    with engine().begin() as c:
        c.execute(text("DELETE FROM users WHERE username = 'zz-lock-test'"))


def test_account_locks_after_repeated_failures_even_for_the_right_password(client, temp_user):
    n = get_settings().login_max_failures
    codes = [_login(client, temp_user, "wrong").status_code for _ in range(n)]
    assert codes == [401] * (n - 1) + [429]  # the last failure triggers the lock
    r = _login(client, temp_user, "right-password")
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0 and "นาที" in r.json()["detail"]
    with engine().begin() as c:  # lock expires
        c.execute(text("UPDATE users SET locked_until = now() - interval '1 second' WHERE username = :u"), {"u": temp_user})
    assert _login(client, temp_user, "right-password").status_code == 200
    with engine().connect() as c:
        assert c.execute(text("SELECT failed_logins FROM users WHERE username = :u"), {"u": temp_user}).scalar_one() == 0


def test_unknown_usernames_are_throttled_the_same_way(client):
    n = get_settings().login_max_failures
    codes = [_login(client, "no-such-user", "x").status_code for _ in range(n)]
    assert codes == [401] * (n - 1) + [429]  # indistinguishable from a real account


def test_a_few_typos_do_not_lock_an_account(client, temp_user):
    for _ in range(get_settings().login_max_failures - 1):
        assert _login(client, temp_user, "typo").status_code == 401
    assert _login(client, temp_user, "right-password").status_code == 200
    for _ in range(get_settings().login_max_failures - 1):  # the counter restarted
        assert _login(client, temp_user, "typo").status_code == 401


def test_login_is_limited_per_client_address(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "rate_login_ip_per_min", 3)
    assert [_login(client, f"spray{i}", "x").status_code for i in range(4)] == [401, 401, 401, 429]


def test_chat_is_rate_limited_per_user_and_the_violation_is_audited(client, fake_llm, monkeypatch):
    monkeypatch.setattr(get_settings(), "rate_chat_per_min", 2)
    def hdr(u, p):
        return {"Authorization": f"Bearer {_login(client, u, p).json()['access_token']}"}
    somchai, nida = hdr("somchai", "demo-employee"), hdr("nida", "demo-compliance")
    q = {"question": "ต้องเก็บข้อมูล CDD กี่ปีหลังปิดบัญชี"}
    ids = []
    for _ in range(2):
        r = client.post("/chat", headers=somchai, json=q)
        assert r.status_code == 200
        ids.append(r.json().get("conversation_id"))
    r = client.post("/chat", headers=somchai, json=q)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1
    other = client.post("/chat", headers=nida, json=q)
    assert other.status_code == 200  # other users unaffected
    assert client.get("/me", headers=somchai).status_code == 200  # only the expensive endpoint is throttled
    audit = client.get("/audit?event=rate_limited", headers=nida)
    assert audit.status_code == 200 and any(e["payload"].get("scope") == "chat" for e in audit.json())
    for c, who in [*[(i, somchai) for i in ids], (other.json().get("conversation_id"), nida)]:
        if c:  # keep the shared dev history clean
            client.post(f"/conversations/{c}/delete", headers=who)


def test_responses_carry_security_headers_and_are_not_cacheable(client):
    r = client.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "no-store" and r.headers["referrer-policy"] == "no-referrer"


def test_password_login_can_be_disabled_for_sso_only_deployments(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "password_login", False)
    assert _login(client, "somchai", "demo-employee").status_code == 404


def test_production_refuses_unsafe_defaults(client, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "env", "production")
    monkeypatch.setattr(s, "jwt_secret", "dev-only-change-me")
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        security.check_production_ready()
    monkeypatch.setattr(s, "jwt_secret", "x" * 40)
    with pytest.raises(RuntimeError, match="published password"):  # demo users are seeded
        security.check_production_ready()
    monkeypatch.setattr(s, "password_login", False)  # SSO-only: demo passwords can never be used
    security.check_production_ready()
    monkeypatch.setattr(s, "env", "development")
    monkeypatch.setattr(s, "jwt_secret", "dev-only-change-me")
    security.check_production_ready()  # laptops stay easy
