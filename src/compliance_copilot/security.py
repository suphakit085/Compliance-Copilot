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

from . import ratelimit, terms
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


ROLES = ("employee", "compliance_officer", "auditor", "admin")
MIN_PASSWORD = 12


def create_user(username: str, display_name: str, role: str, department: str, clearance: str,
                password: str, update: bool = False) -> None:
    """Create a local account (for the first admin of a deployment, or break-glass access when SSO
    is down). Day-to-day users should come from the identity provider."""
    if role not in ROLES:
        raise ValueError(f"role must be one of {', '.join(ROLES)}")
    if clearance not in CLEARANCE:
        raise ValueError(f"clearance must be one of {', '.join(CLEARANCE)}")
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"password must be at least {MIN_PASSWORD} characters")
    init_db()
    with session() as db:
        u = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
        if u and not update:
            raise ValueError(f"user '{username}' already exists (use --update to change it)")
        u = u or User(username=username)
        u.display_name, u.role, u.department = display_name, role, department
        u.clearance, u.active = CLEARANCE[clearance], True
        u.password_hash = hash_password(password)
        u.failed_logins, u.locked_until = 0, None
        db.add(u)


def to_context(u: User) -> UserContext:
    return UserContext(u.id, u.username, u.role, u.department, u.clearance, u.display_name,
                       terms_ok=terms.accepted(u.terms_version))


class LoginLocked(Exception):
    """Too many failed attempts; ``retry_after`` is in seconds."""

    def __init__(self, retry_after: float, newly_locked: bool = False, username: str | None = None):
        super().__init__("login temporarily locked")
        self.retry_after, self.newly_locked, self.username = retry_after, newly_locked, username


_DUMMY_HASH = hash_password("not-a-real-password")  # equalises timing for unknown usernames


def authenticate(username: str, password: str) -> UserContext | None:
    """Verify a password. Raises LoginLocked after repeated failures.

    Lockout state is kept in the database for real accounts (survives restarts and is shared
    by replicas) and in memory for unknown usernames, with the same threshold and duration, so
    an attacker cannot tell the two apart.
    """
    s = get_settings()
    window = s.login_lock_minutes * 60
    guess_key = f"login-guess:{username.lower()}"
    now = datetime.now(UTC)
    with session() as db:
        u = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
        if u and u.locked_until and u.locked_until > now:
            raise LoginLocked((u.locked_until - now).total_seconds())
        if not u:
            if (retry := ratelimit.limiter.hit(guess_key, s.login_max_failures - 1, window)[0]):  # same count as real accounts
                raise LoginLocked(retry)
            check_password(password, _DUMMY_HASH)
            return None
        if u.active and check_password(password, u.password_hash):
            u.failed_logins, u.locked_until = 0, None
            return to_context(u)
        if not u.active:
            check_password(password, _DUMMY_HASH)
        u.failed_logins = (u.failed_logins or 0) + 1
        if u.failed_logins >= s.login_max_failures:
            u.failed_logins = 0
            u.locked_until = now + timedelta(seconds=window)
            db.commit()
            raise LoginLocked(window, newly_locked=True, username=u.username)
        return None


def demo_accounts_with_published_passwords() -> list[str]:
    """Active accounts whose password is still one published in config/users.yaml."""
    data = yaml.safe_load((ROOT / "config" / "users.yaml").read_text(encoding="utf-8"))
    known = {u["username"]: u["password"] for u in data["users"]}
    with session() as db:
        return [u.username for u in db.execute(select(User).where(User.active.is_(True))).scalars()
                if u.username in known and check_password(known[u.username], u.password_hash)]


def check_production_ready() -> None:
    """Refuse to start in production with settings that are only acceptable on a laptop."""
    s = get_settings()
    if s.env != "production":
        return
    problems = []
    if s.jwt_secret == "dev-only-change-me" or len(s.jwt_secret) < 32:
        problems.append("COPILOT_JWT_SECRET must be a random value of at least 32 characters")
    if s.password_login:
        problems += [f"demo account '{u}' still has its published password" for u in demo_accounts_with_published_passwords()]
    if problems:
        raise RuntimeError("unsafe production configuration:\n  - " + "\n  - ".join(problems))


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
