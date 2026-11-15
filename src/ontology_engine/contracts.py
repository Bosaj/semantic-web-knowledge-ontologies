"""Typed DTOs, protocols, errors, and dependency injection container."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol


class DomainError(Exception):
    """Base domain exception."""


class ValidationError(DomainError):
    """Raised when triple or query constraints are violated."""


class OntologyParseError(DomainError):
    """Raised when an RDF/XML ontology payload is malformed."""


@dataclass(frozen=True, slots=True)
class RdfTriple:
    """Immutable RDF triple."""

    subject: str
    predicate: str
    obj: str


@dataclass(frozen=True, slots=True)
class TriplePattern:
    """BGP clause where '?name' tokens represent query variables."""

    subject: str
    predicate: str
    obj: str


@dataclass(frozen=True, slots=True)
class QueryBinding:
    """Single variable binding row returned by pattern evaluation."""

    bindings: dict[str, str]


@dataclass(frozen=True, slots=True)
class ReasoningSummary:
    """Entailment statistics produced by RDFS fixpoint reasoning."""

    asserted_triples: int
    inferred_triples: int
    total_triples: int
    iterations: int


class MetricsSink(Protocol):
    """Observability contract for counters and timings."""

    def increment(self, metric: str, value: int = 1, **tags: str) -> None: ...

    def observe_ms(self, metric: str, duration_ms: float, **tags: str) -> None: ...


class TripleStoreProtocol(Protocol):
    """Abstract triple store interface decoupled from concrete storage."""

    def add_all(self, triples: list[RdfTriple]) -> None: ...

    def all_triples(self) -> set[RdfTriple]: ...


class InMemoryTripleStore:
    """Set-backed in-memory RDF triple repository."""

    def __init__(self) -> None:
        self._triples: set[RdfTriple] = set()

    def add_all(self, triples: list[RdfTriple]) -> None:
        self._triples.update(triples)

    def all_triples(self) -> set[RdfTriple]:
        return set(self._triples)


class OntologyContainer:
    """Singleton dependency injection container."""

    def __init__(self) -> None:
        self._factories: dict[type[Any], Callable[[OntologyContainer], Any]] = {}
        self._singletons: dict[type[Any], Any] = {}

    def register_singleton(
        self, interface: type[Any], factory: Callable[[OntologyContainer], Any]
    ) -> None:
        self._factories[interface] = factory
        self._singletons.pop(interface, None)

    def resolve(self, interface: type[Any]) -> Any:
        if interface in self._singletons:
            return self._singletons[interface]
        factory = self._factories.get(interface)
        if factory is None:
            raise KeyError(f"No provider registered for {interface.__name__}")
        instance = factory(self)
        self._singletons[interface] = instance
        return instance
