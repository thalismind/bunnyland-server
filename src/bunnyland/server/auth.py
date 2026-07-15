"""Opaque bearer-token authentication for Bunnyland HTTP clients."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Annotated, Literal

import yaml
from fastapi import Depends, HTTPException, Request
from fastapi.security import APIKeyCookie, HTTPAuthorizationCredentials, HTTPBearer, SecurityScopes
from pydantic import BaseModel, Field

WORLD_PLAY_SCOPE = "world:play"
WORLD_ADMIN_SCOPE = "world:admin"
AUTH_COOKIE_NAME = "bunnyland_token"
HUMAN_TOKEN_LIFETIME_SECONDS = 7 * 24 * 60 * 60
HUMAN_ROTATE_AFTER_SECONDS = 24 * 60 * 60
AUTOMATION_TOKEN_LIFETIME_SECONDS = 90 * 24 * 60 * 60
ROTATION_GRACE_SECONDS = 30

_TOKEN_RE = re.compile(r"^blt_([a-f0-9]{16})_([A-Za-z0-9_-]{32,})$")
_bearer_scheme = HTTPBearer(auto_error=False)
_cookie_scheme = APIKeyCookie(name=AUTH_COOKIE_NAME, auto_error=False)


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(loader, node, deep=False):
    seen: set[object] = set()
    for key_node, _value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                "while constructing authentication users",
                node.start_mark,
                "duplicate key is not allowed",
                key_node.start_mark,
            )
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)
    delivery: Literal["cookie", "body"] = "cookie"


class TokenResponse(BaseModel):
    token: str | None = None
    token_type: Literal["bearer"] = "bearer"
    subject: str
    scopes: list[str]
    expires_at: int
    rotate_after: int | None
    rotation_eligible: bool


class AuthMeResponse(BaseModel):
    subject: str
    scopes: list[str]
    expires_at: int
    rotate_after: int | None
    rotation_eligible: bool


@dataclass(frozen=True)
class UserCredential:
    username: str
    password_hash: str
    enabled: bool
    scopes: frozenset[str]


@dataclass(frozen=True)
class TokenPrincipal:
    token_id: str
    subject: str
    scopes: frozenset[str]
    created_at: int
    rotate_after: int | None
    expires_at: int
    automatic_rotation: bool
    family_id: str

    def can_rotate(self, *, now: int | None = None) -> bool:
        current = int(time.time()) if now is None else now
        return bool(
            self.automatic_rotation
            and self.rotate_after is not None
            and self.rotate_after <= current < self.expires_at
        )


def normalized_scopes(
    scopes: list[str] | tuple[str, ...] | set[str] | frozenset[str],
) -> frozenset[str]:
    result = {scope.strip() for scope in scopes if isinstance(scope, str) and scope.strip()}
    if WORLD_ADMIN_SCOPE in result:
        result.add(WORLD_PLAY_SCOPE)
    return frozenset(result)


class UserCredentialStore:
    """Read manually provisioned users from a deployment-rendered YAML file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _load(self, *, strict: bool = False) -> dict[str, UserCredential]:
        try:
            raw = yaml.load(self.path.read_text(), Loader=_UniqueKeyLoader) or {}
        except yaml.constructor.ConstructorError as exc:
            if strict and "duplicate key" in str(exc):
                raise ValueError("authentication user file contains duplicate YAML keys") from exc
            if strict:
                raise ValueError(
                    f"authentication user file is not readable YAML: {self.path}"
                ) from exc
            return {}
        except (OSError, yaml.YAMLError, UnicodeError) as exc:
            if strict:
                raise ValueError(
                    f"authentication user file is not readable YAML: {self.path}"
                ) from exc
            return {}
        entries = raw.get("users", raw) if isinstance(raw, dict) else raw
        if isinstance(entries, dict):
            mapped_entries = []
            for key, value in entries.items():
                if not isinstance(value, dict):
                    if strict:
                        raise ValueError("authentication user entries must be mappings")
                    continue
                mapped_entries.append(dict(value, username=key))
            entries = mapped_entries
        if not isinstance(entries, list):
            if strict:
                raise ValueError("authentication user file must contain a users list or mapping")
            return {}
        users: dict[str, UserCredential] = {}
        for entry in entries:
            if not isinstance(entry, dict):
                if strict:
                    raise ValueError("authentication user entries must be mappings")
                continue
            username = str(entry.get("username", "")).strip()
            password_hash = str(entry.get("password_hash", "")).strip()
            if not username or not password_hash:
                if strict:
                    raise ValueError(
                        "authentication users require non-empty username and password_hash"
                    )
                continue
            if username in users:
                raise ValueError(f"duplicate authentication username: {username!r}")
            scopes = entry.get("scopes", [])
            if not isinstance(scopes, list):
                if strict:
                    raise ValueError(f"authentication scopes for {username!r} must be a list")
                scopes = []
            enabled = entry.get("enabled", True)
            if strict and not isinstance(enabled, bool):
                raise ValueError(f"authentication enabled for {username!r} must be a boolean")
            if strict and not scopes:
                raise ValueError(f"authentication scopes for {username!r} must not be empty")
            if strict and any(
                not isinstance(scope, str)
                or scope not in {WORLD_PLAY_SCOPE, WORLD_ADMIN_SCOPE}
                for scope in scopes
            ):
                raise ValueError(
                    f"authentication scopes for {username!r} must be world:play or world:admin"
                )
            users[username] = UserCredential(
                username=username,
                password_hash=password_hash,
                enabled=enabled if isinstance(enabled, bool) else bool(enabled),
                scopes=normalized_scopes(scopes),
            )
        return users

    def validate(self) -> None:
        """Fail before listening when the deployment credential file is unusable."""

        try:
            from pwdlib import PasswordHash
            from pwdlib.exceptions import UnknownHashError
        except ImportError as exc:
            raise RuntimeError("password login requires pwdlib[argon2]") from exc
        users = self._load(strict=True)
        if not users:
            raise ValueError("authentication user file must contain at least one user")
        try:
            verifier = PasswordHash.recommended()
        except (ImportError, RuntimeError) as exc:
            raise RuntimeError("password login requires pwdlib[argon2]") from exc
        for username, user in users.items():
            if not user.password_hash.startswith(("$argon2id$", "$argon2i$", "$argon2d$")):
                raise ValueError(f"invalid Argon2 password hash for user {username!r}")
            try:
                verifier.verify("bunnyland-startup-validation", user.password_hash)
            except (TypeError, ValueError, UnknownHashError) as exc:
                raise ValueError(f"invalid Argon2 password hash for user {username!r}") from exc

    def authenticate(self, username: str, password: str) -> UserCredential | None:
        user = self._load().get(username)
        try:
            from pwdlib import PasswordHash
            from pwdlib.exceptions import UnknownHashError
        except ImportError as exc:
            raise RuntimeError("password login requires pwdlib[argon2]") from exc
        try:
            candidate_hash = (
                user.password_hash if user is not None and user.enabled else _dummy_password_hash()
            )
            valid = PasswordHash.recommended().verify(password, candidate_hash)
        except (TypeError, ValueError, UnknownHashError):
            valid = False
        return user if user is not None and user.enabled and valid else None


@lru_cache(maxsize=1)
def _dummy_password_hash() -> str:
    """Return one process-local Argon2 hash for constant-work rejected logins."""
    from pwdlib import PasswordHash

    return PasswordHash.recommended().hash(secrets.token_urlsafe(32))


def hash_password(password: str) -> str:
    from pwdlib import PasswordHash

    return PasswordHash.recommended().hash(password)


class TokenStore:
    """Private SQLite store containing token digests and revocation metadata."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        if self.path != ":memory:":
            Path(self.path).chmod(0o600)
        self._connection.row_factory = sqlite3.Row
        self._lock = Lock()
        with self._connection:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_tokens (
                    token_id TEXT PRIMARY KEY,
                    digest TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    scopes TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    rotate_after INTEGER,
                    expires_at INTEGER NOT NULL,
                    automatic_rotation INTEGER NOT NULL,
                    family_id TEXT NOT NULL,
                    revoked_at INTEGER,
                    grace_until INTEGER,
                    replaced_by TEXT
                )
                """
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS auth_tokens_subject ON auth_tokens(subject)"
            )
        self._lock_permissions()

    def _lock_permissions(self) -> None:
        if self.path == ":memory:":
            return
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(f"{self.path}{suffix}")
            if candidate.exists():
                candidate.chmod(0o600)

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    @staticmethod
    def _digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _new_token() -> tuple[str, str]:
        token_id = secrets.token_hex(8)
        token = f"blt_{token_id}_{secrets.token_urlsafe(32)}"
        return token_id, token

    @staticmethod
    def _principal(row: sqlite3.Row) -> TokenPrincipal:
        return TokenPrincipal(
            token_id=row["token_id"],
            subject=row["subject"],
            scopes=normalized_scopes(json.loads(row["scopes"])),
            created_at=row["created_at"],
            rotate_after=row["rotate_after"],
            expires_at=row["expires_at"],
            automatic_rotation=bool(row["automatic_rotation"]),
            family_id=row["family_id"],
        )

    def issue(
        self,
        subject: str,
        scopes: list[str] | tuple[str, ...] | set[str] | frozenset[str],
        *,
        automatic_rotation: bool,
        lifetime_seconds: int | None = None,
        now: int | None = None,
        family_id: str | None = None,
    ) -> tuple[str, TokenPrincipal]:
        current = int(time.time()) if now is None else now
        lifetime = lifetime_seconds or (
            HUMAN_TOKEN_LIFETIME_SECONDS
            if automatic_rotation
            else AUTOMATION_TOKEN_LIFETIME_SECONDS
        )
        token_id, token = self._new_token()
        family = family_id or secrets.token_hex(16)
        rotate_after = current + HUMAN_ROTATE_AFTER_SECONDS if automatic_rotation else None
        normalized = normalized_scopes(scopes)
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO auth_tokens (
                    token_id, digest, subject, scopes, created_at, rotate_after, expires_at,
                    automatic_rotation, family_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    token_id,
                    self._digest(token),
                    subject,
                    json.dumps(sorted(normalized), separators=(",", ":")),
                    current,
                    rotate_after,
                    current + lifetime,
                    int(automatic_rotation),
                    family,
                ),
            )
            row = self._connection.execute(
                "SELECT * FROM auth_tokens WHERE token_id = ?", (token_id,)
            ).fetchone()
        self._lock_permissions()
        return token, self._principal(row)

    def import_digest(
        self,
        token_id: str,
        digest: str,
        subject: str,
        scopes: list[str] | tuple[str, ...],
        *,
        expires_at: int,
        created_at: int | None = None,
    ) -> bool:
        """Import or reconcile operator-generated automation-token metadata."""
        if not re.fullmatch(r"[0-9a-f]{16}", token_id):
            raise ValueError("token id must be 16 lowercase hexadecimal characters")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("digest must be a lowercase SHA-256 hexadecimal digest")
        created = int(time.time()) if created_at is None else created_at
        normalized = normalized_scopes(scopes)
        with self._lock, self._connection:
            scopes_json = json.dumps(sorted(normalized), separators=(",", ":"))
            existing = self._connection.execute(
                "SELECT digest, subject, scopes, expires_at FROM auth_tokens WHERE token_id = ?",
                (token_id,),
            ).fetchone()
            if existing is not None:
                if not secrets.compare_digest(existing["digest"], digest):
                    raise ValueError("token id already exists with a different digest")
                changed = (
                    existing["subject"] != subject
                    or existing["scopes"] != scopes_json
                    or existing["expires_at"] != expires_at
                )
                if changed:
                    self._connection.execute(
                        """
                        UPDATE auth_tokens SET subject = ?, scopes = ?, expires_at = ?
                        WHERE token_id = ?
                        """,
                        (subject, scopes_json, expires_at, token_id),
                    )
            else:
                self._connection.execute(
                    """
                    INSERT INTO auth_tokens (
                        token_id, digest, subject, scopes, created_at, rotate_after, expires_at,
                        automatic_rotation, family_id
                    ) VALUES (?, ?, ?, ?, ?, NULL, ?, 0, ?)
                    """,
                    (
                        token_id,
                        digest,
                        subject,
                        scopes_json,
                        created,
                        expires_at,
                        secrets.token_hex(16),
                    ),
                )
                changed = True
        self._lock_permissions()
        return changed

    def verify(self, token: str, *, now: int | None = None) -> TokenPrincipal | None:
        match = _TOKEN_RE.fullmatch(token)
        if match is None:
            return None
        token_id = match.group(1)
        current = int(time.time()) if now is None else now
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM auth_tokens WHERE token_id = ?", (token_id,)
            ).fetchone()
        if row is None or not secrets.compare_digest(row["digest"], self._digest(token)):
            return None
        if row["expires_at"] <= current:
            return None
        if row["revoked_at"] is not None and (
            row["grace_until"] is None or row["grace_until"] <= current
        ):
            return None
        return self._principal(row)

    def rotate(
        self,
        token: str,
        *,
        now: int | None = None,
        grace_seconds: int = ROTATION_GRACE_SECONDS,
    ) -> tuple[str, TokenPrincipal]:
        current = int(time.time()) if now is None else now
        match = _TOKEN_RE.fullmatch(token)
        if match is None:
            raise PermissionError("invalid token")
        source_id = match.group(1)
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._connection.execute(
                    "SELECT * FROM auth_tokens WHERE token_id = ?", (source_id,)
                ).fetchone()
                if (
                    row is None
                    or not secrets.compare_digest(row["digest"], self._digest(token))
                    or row["expires_at"] <= current
                ):
                    raise PermissionError("invalid token")
                principal = self._principal(row)
                if not principal.automatic_rotation:
                    raise PermissionError("token requires manual rotation")
                if not principal.can_rotate(now=current):
                    raise ValueError("token is not eligible for rotation")
                if row["replaced_by"] is not None:
                    raise ValueError("token has already been rotated")
                if row["revoked_at"] is not None:
                    raise PermissionError("invalid token")

                replacement_id, replacement = self._new_token()
                replacement_rotate_after = current + HUMAN_ROTATE_AFTER_SECONDS
                replacement_expires_at = current + HUMAN_TOKEN_LIFETIME_SECONDS
                self._connection.execute(
                    """
                    INSERT INTO auth_tokens (
                        token_id, digest, subject, scopes, created_at, rotate_after,
                        expires_at, automatic_rotation, family_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
                    """,
                    (
                        replacement_id,
                        self._digest(replacement),
                        principal.subject,
                        json.dumps(sorted(principal.scopes), separators=(",", ":")),
                        current,
                        replacement_rotate_after,
                        replacement_expires_at,
                        principal.family_id,
                    ),
                )
                self._connection.execute(
                    """
                    UPDATE auth_tokens
                    SET revoked_at = ?, grace_until = ?, replaced_by = ?
                    WHERE token_id = ? AND replaced_by IS NULL AND revoked_at IS NULL
                    """,
                    (
                        current,
                        current + grace_seconds,
                        replacement_id,
                        principal.token_id,
                    ),
                )
                replacement_row = self._connection.execute(
                    "SELECT * FROM auth_tokens WHERE token_id = ?", (replacement_id,)
                ).fetchone()
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
        self._lock_permissions()
        return replacement, self._principal(replacement_row)

    def revoke_token(self, token_or_id: str, *, now: int | None = None) -> bool:
        current = int(time.time()) if now is None else now
        match = _TOKEN_RE.fullmatch(token_or_id)
        token_id = match.group(1) if match else token_or_id
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                UPDATE auth_tokens SET revoked_at = ?, grace_until = NULL
                WHERE token_id = ? AND (revoked_at IS NULL OR grace_until IS NOT NULL)
                """,
                (current, token_id),
            )
        self._lock_permissions()
        return cursor.rowcount > 0

    def revoke_subject(self, subject: str, *, now: int | None = None) -> int:
        current = int(time.time()) if now is None else now
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                UPDATE auth_tokens SET revoked_at = ?, grace_until = NULL
                WHERE subject = ? AND (revoked_at IS NULL OR grace_until IS NOT NULL)
                """,
                (current, subject),
            )
        self._lock_permissions()
        return cursor.rowcount

    def replace(self, token_id: str, *, now: int | None = None) -> tuple[str, TokenPrincipal]:
        current = int(time.time()) if now is None else now
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM auth_tokens WHERE token_id = ?", (token_id,)
            ).fetchone()
        if row is None:
            raise KeyError(token_id)
        replacement, principal = self.issue(
            row["subject"],
            json.loads(row["scopes"]),
            automatic_rotation=bool(row["automatic_rotation"]),
            now=current,
            family_id=row["family_id"],
        )
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE auth_tokens
                SET revoked_at = ?, grace_until = NULL, replaced_by = ?
                WHERE token_id = ?
                """,
                (current, principal.token_id, token_id),
            )
        self._lock_permissions()
        return replacement, principal

    def list_metadata(self) -> list[dict[str, object]]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT token_id, subject, scopes, created_at, rotate_after, expires_at,
                       automatic_rotation, family_id, revoked_at, grace_until, replaced_by
                FROM auth_tokens ORDER BY created_at, token_id
                """
            ).fetchall()
        return [
            {
                **dict(row),
                "scopes": json.loads(row["scopes"]),
                "automatic_rotation": bool(row["automatic_rotation"]),
            }
            for row in rows
        ]


class RequestAuthenticator:
    """FastAPI security dependency accepting the bearer header or secure cookie."""

    def __init__(self, tokens: TokenStore) -> None:
        self.tokens = tokens

    @staticmethod
    def _unauthorized(detail: str = "invalid or expired bearer token") -> HTTPException:
        return HTTPException(
            status_code=401,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )

    def authenticate_values(
        self,
        *,
        authorization: str | None,
        cookie_token: str | None,
        required_scopes: tuple[str, ...] = (),
    ) -> TokenPrincipal:
        header_token = None
        if authorization:
            scheme, separator, value = authorization.partition(" ")
            if not separator or scheme.lower() != "bearer" or not value.strip():
                raise self._unauthorized()
            header_token = value.strip()
        if header_token and cookie_token and not secrets.compare_digest(header_token, cookie_token):
            raise self._unauthorized("conflicting bearer credentials")
        token = header_token or cookie_token
        if not token:
            raise self._unauthorized("bearer token required")
        principal = self.tokens.verify(token)
        if principal is None:
            raise self._unauthorized()
        missing = [scope for scope in required_scopes if scope not in principal.scopes]
        if missing:
            raise HTTPException(status_code=403, detail="insufficient token scope")
        return principal

    def authenticate_request(
        self,
        request: Request,
        *,
        required_scopes: tuple[str, ...] = (),
    ) -> TokenPrincipal:
        existing = getattr(request.state, "auth_principal", None)
        if isinstance(existing, TokenPrincipal):
            missing = [scope for scope in required_scopes if scope not in existing.scopes]
            if missing:
                raise HTTPException(status_code=403, detail="insufficient token scope")
            return existing
        principal = self.authenticate_values(
            authorization=request.headers.get("Authorization"),
            cookie_token=request.cookies.get(AUTH_COOKIE_NAME),
            required_scopes=required_scopes,
        )
        request.state.auth_principal = principal
        return principal

    async def __call__(
        self,
        security_scopes: SecurityScopes,
        request: Request,
        bearer: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
        cookie_token: Annotated[str | None, Depends(_cookie_scheme)],
    ) -> TokenPrincipal:
        # Read the raw header as well so malformed/non-Bearer credentials are rejected.
        authorization = request.headers.get("Authorization")
        if bearer is not None:
            authorization = f"{bearer.scheme} {bearer.credentials}"
        existing = getattr(request.state, "auth_principal", None)
        if isinstance(existing, TokenPrincipal):
            principal = existing
            missing = [scope for scope in security_scopes.scopes if scope not in principal.scopes]
            if missing:
                raise HTTPException(status_code=403, detail="insufficient token scope")
            return principal
        principal = self.authenticate_values(
            authorization=authorization,
            cookie_token=cookie_token,
            required_scopes=tuple(security_scopes.scopes),
        )
        request.state.auth_principal = principal
        return principal


__all__ = [
    "AUTH_COOKIE_NAME",
    "AUTOMATION_TOKEN_LIFETIME_SECONDS",
    "AuthMeResponse",
    "HUMAN_ROTATE_AFTER_SECONDS",
    "HUMAN_TOKEN_LIFETIME_SECONDS",
    "LoginRequest",
    "ROTATION_GRACE_SECONDS",
    "RequestAuthenticator",
    "TokenPrincipal",
    "TokenResponse",
    "TokenStore",
    "UserCredentialStore",
    "WORLD_ADMIN_SCOPE",
    "WORLD_PLAY_SCOPE",
    "hash_password",
    "normalized_scopes",
]
