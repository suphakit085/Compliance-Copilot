"""Authentication (demo users + JWT) and role-based authorisation.

Production would replace ``authenticate`` with the bank's SSO (OIDC); everything
downstream only depends on the ``UserContext`` (role, department, clearance).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from datetime import UTC, datetime, timedelta

import jwt
import yaml
from sqlalchemy import select

from .config import ROOT, get_settings
from .db import CLEARANCE, User, init_db, session
from .retrieval.retriever import UserContext

ROLES_AUDIT = {"compliance_officer", "auditor", "admin"}
ROLES_GAP = {"compliance_officer", "admin"}


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def check_password(password: str, stored: str) -> bool:
    try:
        _, salt_b64, digest_b64 = stored.split("$")
    except ValueError:
        return False
    expected = hash_password(password, base64.b64decode(salt_b64)).split("$")[2]
    return hmac.compare_digest(expected, digest_b64)


def seed_users(path=None) -> int:
    init_db()
    data = yaml.safe_load((path or ROOT / "config" / "users.yaml").read_text(encoding="utf-8"))
    n = 0
    with session() as db:
        for u in data["users"]:
            row = db.execute(select(User).where(User.username == u["username"])).scalar_one_or_none()
            row = row or User(username=u["username"])
            row.display_name = u["display_name"]
            row.role = u["role"]
            row.department = u["department"]
            row.clearance = CLEARANCE[u["clearance"]]
            row.password_hash = hash_password(u["password"])
            row.active = True
            db.add(row)
            n += 1
    return n


def to_context(u: User) -> UserContext:
    return UserContext(u.id, u.username, u.role, u.department, u.clearance, u.display_name)


def authenticate(username: str, password: str) -> UserContext | None:
    with session() as db:
        u = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
        if not u or not u.active or not check_password(password, u.password_hash):
            return None
        return to_context(u)


def issue_token(user: UserContext) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    return jwt.encode(
        {"sub": str(user.id), "iat": now, "exp": now + timedelta(minutes=s.jwt_ttl_minutes)},
        s.jwt_secret, algorithm="HS256",
    )


def user_from_token(token: str) -> UserContext | None:
    """Claims carry only the user id; role and clearance are re-read from the DB on every
    request so revoking access takes effect immediately."""
    try:
        claims = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    with session() as db:
        u = db.get(User, int(claims["sub"]))
        return to_context(u) if u and u.active else None
