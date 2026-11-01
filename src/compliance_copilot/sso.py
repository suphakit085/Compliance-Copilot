"""Single sign-on with OpenID Connect (authorization-code flow + PKCE).

The identity provider (Keycloak, Azure AD / Entra ID, Okta ...) proves *who* the user is;
this module turns its ID token into the same ``UserContext`` the demo login produces, so
nothing downstream (RBAC, row-level security, audit) knows or cares how the user signed in.

* the ID token's signature, issuer, audience, expiry and nonce are all verified;
* role, department and clearance come from the IdP's group claim via ``config/sso.yaml`` -
  access is revoked at the IdP and takes effect at the next sign-in;
* users are provisioned on first login and linked by the IdP's stable ``sub`` claim,
  never by username, so a colliding username cannot take over a local account.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import httpx
import jwt
import yaml
from sqlalchemy import select

from .config import ROOT, get_settings
from .db import CLEARANCE, User, session
from .retrieval.retriever import UserContext
from .security import to_context

STATE_TTL = timedelta(minutes=10)


class SSOError(Exception):
    """Sign-in failed; the message is safe to show the user."""


@dataclass(frozen=True)
class Provider:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str


def enabled() -> bool:
    s = get_settings()
    return bool(s.oidc_issuer and s.oidc_client_id)


_lock = threading.Lock()
_provider: Provider | None = None
_jwks: jwt.PyJWKClient | None = None


def provider() -> Provider:
    global _provider, _jwks
    with _lock:
        if _provider is None:
            s = get_settings()
            url = s.oidc_issuer.rstrip("/") + "/.well-known/openid-configuration"
            try:
                doc = httpx.get(url, timeout=10).raise_for_status().json()
            except httpx.HTTPError as e:
                raise SSOError("ไม่สามารถติดต่อระบบ SSO ได้") from e
            _provider = Provider(doc["issuer"], doc["authorization_endpoint"], doc["token_endpoint"], doc["jwks_uri"])
            _jwks = jwt.PyJWKClient(_provider.jwks_uri, cache_keys=True)
        return _provider


def reset() -> None:
    global _provider, _jwks
    with _lock:
        _provider = _jwks = None


@lru_cache
def group_map() -> dict[str, dict]:
    path = get_settings().oidc_group_map or ROOT / "config" / "sso.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)["groups"]


def _pkce_challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def begin() -> tuple[str, str]:
    """Start a sign-in. Returns (URL to send the browser to, signed state token).

    The state token carries the CSRF ``state``, the ``nonce`` and the PKCE verifier; the web
    tier keeps it in an httpOnly cookie and hands it back with the authorization code.
    """
    s, p = get_settings(), provider()
    state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    token = jwt.encode(
        {"state": state, "nonce": nonce, "cv": verifier, "exp": datetime.now(UTC) + STATE_TTL},
        s.jwt_secret, algorithm="HS256",
    )
    query = httpx.QueryParams({
        "response_type": "code", "client_id": s.oidc_client_id, "redirect_uri": s.oidc_redirect_uri,
        "scope": "openid profile email", "state": state, "nonce": nonce,
        "code_challenge": _pkce_challenge(verifier), "code_challenge_method": "S256",
    })
    return f"{p.authorization_endpoint}?{query}", token


def _resolve_access(groups: list[str]) -> dict:
    mapped = [group_map()[g] for g in groups if g in group_map()]
    if not mapped:
        raise SSOError("บัญชีของคุณยังไม่ได้รับสิทธิ์ใช้งานระบบนี้ กรุณาติดต่อผู้ดูแลระบบ")
    return max(mapped, key=lambda m: CLEARANCE[m["clearance"]])


def _provision(issuer: str, claims: dict, access: dict) -> UserContext:
    external_id = f"{issuer}|{claims['sub']}"
    wanted = claims.get("preferred_username") or claims.get("email") or claims["sub"]
    with session() as db:
        u = db.execute(select(User).where(User.external_id == external_id)).scalar_one_or_none()
        if u is None:
            taken = db.execute(select(User.id).where(User.username == wanted)).first()
            u = User(username=f"{wanted}.sso" if taken else wanted, external_id=external_id, password_hash="!", active=True)
        if not u.active:
            raise SSOError("บัญชีนี้ถูกระงับการใช้งาน")
        u.display_name = claims.get("name") or wanted
        u.role, u.department = access["role"], access["department"]
        u.clearance = CLEARANCE[access["clearance"]]
        db.add(u)
        db.flush()
        return to_context(u)


def complete(code: str, state: str, state_token: str) -> UserContext:
    """Finish a sign-in: validate state, exchange the code, verify the ID token, map access."""
    s, p = get_settings(), provider()
    try:
        st = jwt.decode(state_token, s.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as e:
        raise SSOError("การเข้าสู่ระบบหมดอายุ กรุณาลองใหม่") from e
    if not secrets.compare_digest(st["state"], state):
        raise SSOError("การเข้าสู่ระบบไม่ถูกต้อง กรุณาลองใหม่")
    try:
        r = httpx.post(p.token_endpoint, timeout=10, data={
            "grant_type": "authorization_code", "code": code, "redirect_uri": s.oidc_redirect_uri,
            "client_id": s.oidc_client_id, "client_secret": s.oidc_client_secret or "",
            "code_verifier": st["cv"],
        })
    except httpx.HTTPError as e:
        raise SSOError("ไม่สามารถติดต่อระบบ SSO ได้") from e
    if r.status_code != 200 or "id_token" not in r.json():
        raise SSOError("ระบบ SSO ปฏิเสธการเข้าสู่ระบบ")
    id_token = r.json()["id_token"]
    try:
        key = _jwks.get_signing_key_from_jwt(id_token).key  # type: ignore[union-attr]
        claims = jwt.decode(
            id_token, key, algorithms=["RS256", "ES256"], audience=s.oidc_client_id, issuer=p.issuer,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]}, leeway=30,
        )
    except jwt.PyJWTError as e:
        raise SSOError("ตรวจสอบโทเคนจาก SSO ไม่ผ่าน") from e
    if not secrets.compare_digest(str(claims.get("nonce", "")), st["nonce"]):
        raise SSOError("การเข้าสู่ระบบไม่ถูกต้อง กรุณาลองใหม่")
    return _provision(p.issuer, claims, _resolve_access(list(claims.get(s.oidc_groups_claim, []))))
