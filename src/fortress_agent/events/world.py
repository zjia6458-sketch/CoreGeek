from __future__ import annotations

from dataclasses import dataclass

from .base import DomainEvent

EntityId = str | int


@dataclass(frozen=True, slots=True, kw_only=True)
class CellObserved(DomainEvent):
    x: int
    y: int
    terrain: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class CellVisited(DomainEvent):
    actor_id: EntityId
    x: int
    y: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ResourceDiscovered(DomainEvent):
    resource_id: EntityId
    resource_type: str
    x: int
    y: int
    amount: int | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ResourceUpdated(DomainEvent):
    resource_id: EntityId
    amount: int | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ResourceDepleted(DomainEvent):
    resource_id: EntityId
    x: int
    y: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ResourceReplenished(DomainEvent):
    resource_id: EntityId
    resource_type: str
    x: int
    y: int
    amount: int | None
