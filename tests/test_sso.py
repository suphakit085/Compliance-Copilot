"""OIDC sign-in against a fake identity provider (real RSA signatures, no network)."""

import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import text

from compliance_copilot import sso
from compliance_copilot.config import get_settings
from compliance_copilot.db import engine

pytestmark = pytest.mark.integration

ISSUER = "https://idp.test/realms/bank"
CLIENT = "compliance-copilot"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def idp(monkeypatch, corpus):
    s = get_settings()
    monkeypatch.setattr(s, "oidc_issuer", ISSUER)
    monkeypatch.setattr(s, "oidc_client_id", CLIENT)
    monkeypatch.setattr(s, "oidc_client_secret", "test-secret")
    monkeypatch.setattr(sso, "_provider", sso.Provider(ISSUER, f"{ISSUER}/auth", f"{ISSUER}/token", f"{ISSUER}/certs"))
    monkeypatch.setattr(sso, "_jwks", SimpleNamespace(
        get_signing_key_from_jwt=lambda _t: SimpleNamespace(key=KEY.public_key())))
    issued: dict = {}

    def fake_post(url, data=None, **_):
        assert url.endswith("/token") and data["code_verifier"]
        return SimpleNamespace(status_code=200, json=lambda: {"id_token": issued["token"]})

    monkeypatch.setattr(sso.httpx, "post", fake_post)

    def sign_in(sub="u-1", groups=("copilot-employee",), key=KEY, nonce=None, state_token=None, finish=True, **override):
        state_token = state_token or sso.begin()[1]
        st = jwt.decode(state_token, s.jwt_secret, algorithms=["HS256"])
        now = int(time.time())
        claims = {"iss": ISSUER, "aud": CLIENT, "sub": sub, "iat": now, "exp": now + 300,
                  "nonce": nonce or st["nonce"], "preferred_username": "test.sso.user",
                  "name": "ผู้ใช้ SSO", "groups": list(groups), **override}
        issued["token"] = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "k1"})
        return sso.complete("code", st["state"], state_token) if finish else st["state"]

    yield sign_in
    with engine().begin() as c:
        c.execute(text("DELETE FROM users WHERE external_id LIKE :p"), {"p": f"{ISSUER}|%"})


def test_group_membership_decides_access(idp):
    u = idp(groups=["copilot-employee"])
    assert (u.role, u.department, u.clearance) == ("employee", "retail", 1)
    # group changes at the IdP take effect at the next sign-in, on the same account
    again = idp(groups=["copilot-compliance"])
    assert again.id == u.id and (again.role, again.clearance) == ("compliance_officer", 2)
    # several groups: the highest clearance wins
    assert idp(groups=["copilot-employee", "copilot-admin"]).clearance == 3


def test_user_without_a_mapped_group_is_refused(idp):
    with pytest.raises(sso.SSOError):
        idp(groups=["some-other-team"])
    with pytest.raises(sso.SSOError):
        idp(groups=[])


def test_forged_or_mismatched_tokens_are_rejected(idp):
    with pytest.raises(sso.SSOError):  # signed by a key the IdP never published
        idp(key=OTHER_KEY)
    with pytest.raises(sso.SSOError):  # replayed token from another login attempt
        idp(nonce="not-this-login")
    with pytest.raises(sso.SSOError):  # token minted for a different client
        idp(aud="another-app")
    with pytest.raises(sso.SSOError):  # issued by a different IdP
        idp(iss="https://evil.test")
    with pytest.raises(sso.SSOError):  # expired
        idp(exp=int(time.time()) - 3600)


def test_state_mismatch_is_rejected(idp):
    _, state_token = sso.begin()
    with pytest.raises(sso.SSOError):
        sso.complete("code", "attacker-chosen-state", state_token)
    with pytest.raises(sso.SSOError):
        sso.complete("code", "x", "garbage")


def test_idp_username_cannot_take_over_a_local_account(idp):
    # the IdP claims the username "somchai", which is an existing local demo user
    u = idp(sub="u-collide", preferred_username="somchai")
    assert u.username == "somchai.sso" and u.username != "somchai"


def test_suspended_sso_user_is_refused(idp):
    idp(sub="u-susp")
    with engine().begin() as c:
        c.execute(text("UPDATE users SET active = false WHERE external_id = :e"), {"e": f"{ISSUER}|u-susp"})
    with pytest.raises(sso.SSOError):
        idp(sub="u-susp")


def test_sso_users_cannot_use_the_password_login(idp):
    from compliance_copilot.api.main import app

    idp(sub="u-pw", preferred_username="pw.only")
    with TestClient(app) as client:
        for pw in ("", "!", "pw.only"):
            assert client.post("/auth/login", json={"username": "pw.only", "password": pw}).status_code == 401


def test_api_issues_a_session_after_sso(idp):
    from compliance_copilot.api.main import app

    with TestClient(app) as client:
        cfg = client.get("/auth/sso/config").json()
        assert cfg["enabled"]
        start = client.get("/auth/sso/start").json()
        assert start["url"].startswith(f"{ISSUER}/auth?") and "code_challenge_method=S256" in start["url"]
        state = idp(sub="u-api", groups=["copilot-audit"], state_token=start["state_token"], finish=False)
        r = client.post("/auth/sso/callback", json={"code": "c", "state": state, "state_token": start["state_token"]})
        assert r.status_code == 200 and r.json()["user"]["role"] == "auditor"
        tok = {"Authorization": f"Bearer {r.json()['access_token']}"}
        assert client.get("/me", headers=tok).json()["role"] == "auditor"
        assert client.get("/audit", headers=tok).status_code == 200
