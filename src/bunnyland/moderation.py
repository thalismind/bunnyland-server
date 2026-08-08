"""Persistent, platform-identity moderation shared by every player ingress."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from threading import Lock
from typing import Protocol
from uuid import uuid4
from weakref import finalize

from .claims import (
    ClaimOwner,
    ClaimSecretRegistry,
    remove_claim,
    retire_transient_controller,
    spawn_transient_controller,
)
from .core import (
    CharacterComponent,
    LLMControllerComponent,
    SuspendedControllerComponent,
    parse_entity_id,
)
from .core.controllers import ClaimedComponent, ClaimTimeoutComponent
from .core.events import DomainEvent, EventVisibility, event_base
from .core.world_actor import WorldActor


class IdentityKind(StrEnum):
    DISCORD = "discord"
    WEB = "web"
    CLIENT = "client"


class RestrictionKind(StrEnum):
    SUSPENDED = "suspended"
    BANNED = "banned"


class ModerationActionKind(StrEnum):
    KICK = "kick"
    SUSPEND = "suspend"
    BAN = "ban"
    LIFT = "lift"


@dataclass(frozen=True, order=True)
class ModerationIdentity:
    kind: IdentityKind
    id: str

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("moderation identity id must not be empty")
        if self.kind is IdentityKind.DISCORD and not self.id.isdecimal():
            raise ValueError("Discord identity id must be a decimal snowflake")

    @property
    def canonical(self) -> str:
        return f"{self.kind.value}:{self.id}"

    @classmethod
    def parse(cls, value: str) -> ModerationIdentity:
        kind, separator, identity_id = value.strip().partition(":")
        if not separator:
            raise ValueError("target must include discord:, web:, or client:")
        try:
            identity_kind = IdentityKind(kind.lower())
        except ValueError as exc:
            raise ValueError("target kind must be discord, web, or client") from exc
        return cls(identity_kind, identity_id.strip())


@dataclass(frozen=True)
class ModerationRestriction:
    target: ModerationIdentity
    kind: RestrictionKind
    reason: str
    created_at: datetime
    expires_at: datetime | None

    def active_at(self, now: datetime) -> bool:
        return self.expires_at is None or self.expires_at > now


@dataclass(frozen=True)
class ModerationAuditEntry:
    id: str
    action: ModerationActionKind
    target: ModerationIdentity
    actor: ModerationIdentity
    reason: str
    created_at: datetime
    expires_at: datetime | None


class ModerationRestrictedError(PermissionError):
    def __init__(self, restriction: ModerationRestriction) -> None:
        self.restriction = restriction
        super().__init__(f"identity is {restriction.kind.value}")


def _utc_timestamp(value: datetime) -> int:
    if value.tzinfo is None:
        raise ValueError("moderation timestamps must be timezone-aware")
    return int(value.timestamp())


def _from_timestamp(value: int | None) -> datetime | None:
    return datetime.fromtimestamp(value, UTC) if value is not None else None


class ModerationStore:
    """SQLite restrictions and append-only moderation audit history."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = Lock()
        self._finalizer = finalize(self, self._connection.close)
        with self._connection:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS moderation_restrictions (
                    identity_kind TEXT NOT NULL,
                    identity_id TEXT NOT NULL,
                    restriction_kind TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER,
                    PRIMARY KEY (identity_kind, identity_id)
                )
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS moderation_audit (
                    audit_id TEXT PRIMARY KEY,
                    action TEXT NOT NULL,
                    identity_kind TEXT NOT NULL,
                    identity_id TEXT NOT NULL,
                    actor_kind TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER
                )
                """
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS moderation_audit_target "
                "ON moderation_audit(identity_kind, identity_id, created_at)"
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
            self._finalizer()

    @staticmethod
    def suspension_expiration(duration_seconds: int, *, now: datetime | None = None) -> datetime:
        if duration_seconds <= 0:
            raise ValueError("duration_seconds must be positive for suspension")
        current = now or datetime.now(UTC)
        try:
            expiration = current + timedelta(seconds=duration_seconds)
            _utc_timestamp(expiration)
        except (OverflowError, OSError, ValueError) as exc:
            raise ValueError("duration_seconds cannot produce a valid UTC expiration") from exc
        return expiration

    @staticmethod
    def _restriction(row: sqlite3.Row) -> ModerationRestriction:
        return ModerationRestriction(
            target=ModerationIdentity(IdentityKind(row["identity_kind"]), row["identity_id"]),
            kind=RestrictionKind(row["restriction_kind"]),
            reason=row["reason"],
            created_at=datetime.fromtimestamp(row["created_at"], UTC),
            expires_at=_from_timestamp(row["expires_at"]),
        )

    @staticmethod
    def _audit_entry(row: sqlite3.Row) -> ModerationAuditEntry:
        return ModerationAuditEntry(
            id=row["audit_id"],
            action=ModerationActionKind(row["action"]),
            target=ModerationIdentity(IdentityKind(row["identity_kind"]), row["identity_id"]),
            actor=ModerationIdentity(IdentityKind(row["actor_kind"]), row["actor_id"]),
            reason=row["reason"],
            created_at=datetime.fromtimestamp(row["created_at"], UTC),
            expires_at=_from_timestamp(row["expires_at"]),
        )

    def restriction(
        self, target: ModerationIdentity, *, now: datetime | None = None
    ) -> ModerationRestriction | None:
        current = now or datetime.now(UTC)
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT * FROM moderation_restrictions WHERE identity_kind = ? AND identity_id = ?",
                (target.kind.value, target.id),
            ).fetchone()
            if row is None:
                return None
            restriction = self._restriction(row)
            if restriction.active_at(current):
                return restriction
            self._connection.execute(
                "DELETE FROM moderation_restrictions WHERE identity_kind = ? AND identity_id = ?",
                (target.kind.value, target.id),
            )
            return None

    def require_allowed(self, target: ModerationIdentity) -> None:
        restriction = self.restriction(target)
        if restriction is not None:
            raise ModerationRestrictedError(restriction)

    def apply(
        self,
        action: ModerationActionKind,
        target: ModerationIdentity,
        actor: ModerationIdentity,
        reason: str,
        *,
        duration_seconds: int | None = None,
        now: datetime | None = None,
    ) -> ModerationAuditEntry:
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValueError("moderation reason is required")
        current = now or datetime.now(UTC)
        expires_at = None
        if action is ModerationActionKind.SUSPEND:
            if duration_seconds is None:
                raise ValueError("duration_seconds is required for suspension")
            expires_at = self.suspension_expiration(duration_seconds, now=current)
        elif duration_seconds is not None:
            raise ValueError("duration_seconds is only valid for suspension")
        restriction_kind = {
            ModerationActionKind.SUSPEND: RestrictionKind.SUSPENDED,
            ModerationActionKind.BAN: RestrictionKind.BANNED,
        }.get(action)
        audit_id = uuid4().hex
        created_at = _utc_timestamp(current)
        expiration = _utc_timestamp(expires_at) if expires_at is not None else None
        with self._lock, self._connection:
            if restriction_kind is not None:
                self._connection.execute(
                    """
                    INSERT INTO moderation_restrictions (
                        identity_kind, identity_id, restriction_kind, reason,
                        created_at, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(identity_kind, identity_id) DO UPDATE SET
                        restriction_kind = excluded.restriction_kind,
                        reason = excluded.reason,
                        created_at = excluded.created_at,
                        expires_at = excluded.expires_at
                    """,
                    (
                        target.kind.value,
                        target.id,
                        restriction_kind.value,
                        normalized_reason,
                        created_at,
                        expiration,
                    ),
                )
            elif action is ModerationActionKind.LIFT:
                self._connection.execute(
                    "DELETE FROM moderation_restrictions "
                    "WHERE identity_kind = ? AND identity_id = ?",
                    (target.kind.value, target.id),
                )
            self._connection.execute(
                """
                INSERT INTO moderation_audit (
                    audit_id, action, identity_kind, identity_id, actor_kind, actor_id,
                    reason, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    audit_id,
                    action.value,
                    target.kind.value,
                    target.id,
                    actor.kind.value,
                    actor.id,
                    normalized_reason,
                    created_at,
                    expiration,
                ),
            )
        self._lock_permissions()
        return ModerationAuditEntry(
            id=audit_id,
            action=action,
            target=target,
            actor=actor,
            reason=normalized_reason,
            created_at=current,
            expires_at=expires_at,
        )

    def history(
        self,
        *,
        target: ModerationIdentity | None = None,
        action: ModerationActionKind | None = None,
        limit: int = 200,
    ) -> list[ModerationAuditEntry]:
        clauses: list[str] = []
        values: list[str | int] = []
        if target is not None:
            clauses.extend(["identity_kind = ?", "identity_id = ?"])
            values.extend([target.kind.value, target.id])
        if action is not None:
            clauses.append("action = ?")
            values.append(action.value)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        values.append(max(1, min(limit, 1000)))
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM moderation_audit"
                + where
                + " ORDER BY created_at DESC, rowid DESC LIMIT ?",
                values,
            ).fetchall()
        return [self._audit_entry(row) for row in rows]

    def known_identities(self) -> set[ModerationIdentity]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT identity_kind, identity_id FROM moderation_restrictions
                UNION SELECT identity_kind, identity_id FROM moderation_audit
                """
            ).fetchall()
        return {
            ModerationIdentity(IdentityKind(row["identity_kind"]), row["identity_id"])
            for row in rows
        }


class ClosableWebSocket(Protocol):
    async def close(self, *, code: int, reason: str | None = None) -> None: ...


class ModerationConnectionRegistry:
    """Tracks authenticated player sockets so moderation can disconnect them now."""

    def __init__(self) -> None:
        self._connections: dict[ModerationIdentity, set[ClosableWebSocket]] = {}

    def add(self, identity: ModerationIdentity, websocket: ClosableWebSocket) -> None:
        self._connections.setdefault(identity, set()).add(websocket)

    def discard(self, identity: ModerationIdentity, websocket: ClosableWebSocket) -> None:
        sockets = self._connections.get(identity)
        if sockets is None:
            return
        sockets.discard(websocket)
        if not sockets:
            self._connections.pop(identity, None)

    async def close_identity(self, identity: ModerationIdentity, reason: str) -> None:
        sockets = tuple(self._connections.pop(identity, ()))
        if sockets:
            await asyncio.gather(
                *(socket.close(code=1008, reason=reason[:123]) for socket in sockets),
                return_exceptions=True,
            )


class ModerationPerformedEvent(DomainEvent):
    action: ModerationActionKind
    target_kind: IdentityKind
    target_id: str
    administrator: str
    reason: str
    expires_at: datetime | None = None


CancelIdentity = Callable[[ModerationIdentity], Awaitable[None]]


class ModerationService:
    """Coordinates restriction persistence with live session and claim teardown."""

    def __init__(
        self,
        actor: WorldActor,
        store: ModerationStore,
        claim_secrets: ClaimSecretRegistry,
        *,
        token_store: object | None = None,
        connections: ModerationConnectionRegistry | None = None,
        cancel_identity: CancelIdentity | None = None,
    ) -> None:
        self.actor = actor
        self.store = store
        self.claim_secrets = claim_secrets
        self.token_store = token_store
        self.connections = connections or ModerationConnectionRegistry()
        self.cancel_identity = cancel_identity

    def configure_runtime(
        self,
        *,
        token_store: object | None = None,
        cancel_identity: CancelIdentity | None = None,
    ) -> None:
        if token_store is not None:
            self.token_store = token_store
        if cancel_identity is not None:
            self.cancel_identity = cancel_identity

    def require_allowed(self, identity: ModerationIdentity) -> None:
        self.store.require_allowed(identity)

    def _claim_matches(self, claim: ClaimedComponent, target: ModerationIdentity) -> bool:
        if target.kind is IdentityKind.DISCORD:
            return claim.client_kind == "discord" and claim.client_id == target.id
        owner = self.claim_secrets.owner(claim.claim_id)
        if target.kind is IdentityKind.WEB:
            return owner == ClaimOwner("rest", target.id)
        return claim.client_id == target.id and owner in {
            None,
            ClaimOwner("rest", f"embedded:{target.id}"),
        }

    def claims_for(self, target: ModerationIdentity) -> list[tuple[object, ClaimedComponent]]:
        matches: list[tuple[object, ClaimedComponent]] = []
        for controller in self.actor.world.query().with_all([ClaimedComponent]).execute_entities():
            claim = controller.get_component(ClaimedComponent)
            if self._claim_matches(claim, target):
                matches.append((controller, claim))
        return matches

    def known_claim_identities(self) -> set[ModerationIdentity]:
        identities: set[ModerationIdentity] = set()
        for controller in self.actor.world.query().with_all([ClaimedComponent]).execute_entities():
            claim = controller.get_component(ClaimedComponent)
            owner = self.claim_secrets.owner(claim.claim_id)
            if claim.client_kind == "discord":
                identities.add(ModerationIdentity(IdentityKind.DISCORD, claim.client_id))
            elif owner is not None and owner.principal_kind == "rest":
                if owner.subject.startswith("embedded:"):
                    identities.add(
                        ModerationIdentity(
                            IdentityKind.CLIENT,
                            owner.subject.removeprefix("embedded:"),
                        )
                    )
                else:
                    identities.add(ModerationIdentity(IdentityKind.WEB, owner.subject))
            else:
                identities.add(ModerationIdentity(IdentityKind.CLIENT, claim.client_id))
        return identities

    def _fallback_controller(self, controller: object) -> object:
        timeout = (
            controller.get_component(ClaimTimeoutComponent)
            if controller.has_component(ClaimTimeoutComponent)
            else ClaimTimeoutComponent()
        )
        fallback = timeout.fallback_controller.strip().lower().replace("_", "-")
        parsed = parse_entity_id(timeout.fallback_controller)
        if parsed is not None and self.actor.world.has_entity(parsed):
            return self.actor.world.get_entity(parsed)
        if fallback in {"llm", "ai", "agent"}:
            return spawn_transient_controller(
                self.actor.world,
                LLMControllerComponent(
                    profile_name=timeout.llm_profile_name or "default",
                    model=timeout.llm_model,
                    provider=timeout.llm_provider or "ollama",
                ),
            )
        return spawn_transient_controller(
            self.actor.world,
            SuspendedControllerComponent(reason=timeout.fallback_reason or "moderated"),
        )

    def _release_claims(self, target: ModerationIdentity) -> None:
        for controller, claim in self.claims_for(target):
            character_id = parse_entity_id(claim.character_id)
            if character_id is not None and self.actor.world.has_entity(character_id):
                character = self.actor.world.get_entity(character_id)
                if character.has_component(CharacterComponent):
                    fallback = self._fallback_controller(controller)
                    self.actor.assign_controller(character.id, fallback.id)
            remove_claim(controller, self.claim_secrets)
            retire_transient_controller(self.actor, controller.id)

    async def execute(
        self,
        action: ModerationActionKind,
        target: ModerationIdentity,
        administrator: ModerationIdentity,
        reason: str,
        *,
        duration_seconds: int | None = None,
    ) -> ModerationAuditEntry:
        if target == administrator:
            raise PermissionError("administrators cannot moderate their own identity")
        entry = self.store.apply(
            action,
            target,
            administrator,
            reason,
            duration_seconds=duration_seconds,
        )
        if action is not ModerationActionKind.LIFT:
            async with self.actor._lock:
                self._release_claims(target)
            if target.kind is IdentityKind.WEB and self.token_store is not None:
                revoke_subject = getattr(self.token_store, "revoke_subject", None)
                if callable(revoke_subject):
                    revoke_subject(target.id)
            if self.cancel_identity is not None:
                await self.cancel_identity(target)
            await self.connections.close_identity(target, f"moderation {action.value}: {reason}")
        await self.actor.bus.publish(
            ModerationPerformedEvent(
                **event_base(self.actor.epoch, default_visibility=EventVisibility.SYSTEM),
                action=action,
                target_kind=target.kind,
                target_id=target.id,
                administrator=administrator.canonical,
                reason=entry.reason,
                expires_at=entry.expires_at,
            )
        )
        return entry


__all__ = [
    "IdentityKind",
    "ModerationActionKind",
    "ModerationAuditEntry",
    "ModerationConnectionRegistry",
    "ModerationIdentity",
    "ModerationPerformedEvent",
    "ModerationRestrictedError",
    "ModerationRestriction",
    "ModerationService",
    "ModerationStore",
    "RestrictionKind",
]
