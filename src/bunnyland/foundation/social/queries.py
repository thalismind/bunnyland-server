"""Claim-scoped Social questions backed by the bounded graph executor."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from ...core.components import IdentityComponent
from ...core.ecs import parse_entity_id
from ...core.graph_query import ComponentTerm, EdgeTerm, GraphQueryExecutor, GraphQuerySpec
from ...core.perspective import (
    PerspectiveQueryDefinition,
    PerspectiveQueryInput,
)
from .mechanics import ObligationComponent, SocialBond


class SocialQuestionInput(PerspectiveQueryInput):
    """The actor id is injected from the authenticated character claim."""


class EntityIdentity(BaseModel):
    id: str
    name: str
    kind: str


class SocialBondValues(BaseModel):
    affinity: float
    trust: float
    fear: float
    resentment: float
    familiarity: float


class SocialConnection(BaseModel):
    character: EntityIdentity
    bond: SocialBondValues


class OpenObligation(BaseModel):
    obligation: EntityIdentity
    role: Literal["debtor", "creditor"]
    counterparty: EntityIdentity
    debtor: EntityIdentity
    creditor: EntityIdentity
    text: str
    kind: str
    due_epoch: int


def _identity(actor, raw_id: str) -> EntityIdentity:
    entity_id = parse_entity_id(raw_id)
    entity = actor.world.get_entity(entity_id)
    identity = entity.get_component(IdentityComponent)
    return EntityIdentity(id=raw_id, name=identity.name, kind=identity.kind)


def _social_connections(actor, request: SocialQuestionInput):
    rows = GraphQueryExecutor(actor.plugins).execute(
        actor.world,
        GraphQuerySpec(
            terms=(
                EdgeTerm(source="actor", edge="SocialBond", target="connection"),
                ComponentTerm(
                    variable="connection",
                    component="IdentityComponent",
                    fields={"kind": "character"},
                ),
            ),
            bindings={"actor": request.actor_id},
            select=("connection",),
        ),
    )
    actor_id = parse_entity_id(request.actor_id)
    source = actor.world.get_entity(actor_id)
    results = []
    for row in rows:
        target_id = parse_entity_id(row["connection"])
        bond = next(
            edge
            for edge, candidate in source.get_relationships(SocialBond)
            if candidate == target_id
        )
        results.append(
            SocialConnection(
                character=_identity(actor, row["connection"]),
                bond=SocialBondValues(
                    affinity=bond.affinity,
                    trust=bond.trust,
                    fear=bond.fear,
                    resentment=bond.resentment,
                    familiarity=bond.familiarity,
                ),
            ).model_dump(mode="json")
        )
    return results, ("authoritative_ecs", "graph:SocialBond")


def _obligation_rows(actor, actor_id: str, role: Literal["debtor", "creditor"]):
    fixed_variable = role
    return GraphQueryExecutor(actor.plugins).execute(
        actor.world,
        GraphQuerySpec(
            terms=(
                ComponentTerm(
                    variable="obligation",
                    component="ObligationComponent",
                    fields={"status": "open"},
                ),
                ComponentTerm(
                    variable="obligation",
                    component="IdentityComponent",
                    fields={"kind": "obligation"},
                ),
                EdgeTerm(
                    source="obligation",
                    edge="ObligationDebtor",
                    target="debtor",
                ),
                EdgeTerm(
                    source="obligation",
                    edge="ObligationCreditor",
                    target="creditor",
                ),
                ComponentTerm(variable="debtor", component="IdentityComponent"),
                ComponentTerm(variable="creditor", component="IdentityComponent"),
            ),
            bindings={fixed_variable: actor_id},
            select=("obligation", "debtor", "creditor"),
        ),
    )


def _open_obligations(actor, request: SocialQuestionInput):
    results = []
    for role in ("debtor", "creditor"):
        for row in _obligation_rows(actor, request.actor_id, role):
            obligation_id = parse_entity_id(row["obligation"])
            entity = actor.world.get_entity(obligation_id)
            component = entity.get_component(ObligationComponent)
            other_role = "creditor" if role == "debtor" else "debtor"
            results.append(
                OpenObligation(
                    obligation=_identity(actor, row["obligation"]),
                    role=role,
                    counterparty=_identity(actor, row[other_role]),
                    debtor=_identity(actor, row["debtor"]),
                    creditor=_identity(actor, row["creditor"]),
                    text=component.text,
                    kind=component.kind,
                    due_epoch=component.due_epoch,
                ).model_dump(mode="json")
            )
    results.sort(key=lambda item: (item["obligation"]["id"], item["role"]))
    return results, (
        "authoritative_ecs",
        "graph:ObligationComponent+ObligationDebtor+ObligationCreditor",
    )


SOCIAL_PERSPECTIVE_QUERIES = (
    PerspectiveQueryDefinition(
        name="social_connections",
        input_model=SocialQuestionInput,
        execute=_social_connections,
        provenance=("claim_scoped",),
    ),
    PerspectiveQueryDefinition(
        name="open_obligations",
        input_model=SocialQuestionInput,
        execute=_open_obligations,
        provenance=("claim_scoped",),
    ),
)


__all__ = [
    "EntityIdentity",
    "OpenObligation",
    "SOCIAL_PERSPECTIVE_QUERIES",
    "SocialBondValues",
    "SocialConnection",
    "SocialQuestionInput",
]
