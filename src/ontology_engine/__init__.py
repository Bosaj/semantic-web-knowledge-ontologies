"""Modular Semantic Web & RDFS reasoning domain architecture."""

from .contracts import (
    DomainError,
    OntologyContainer,
    OntologyParseError,
    QueryBinding,
    RdfTriple,
    ReasoningSummary,
    TriplePattern,
    ValidationError,
)
from .reasoner import (
    RdfsClosureReasoner,
    TriplePatternMatcher,
    XmlOntologyParser,
)
from .telemetry import InMemoryMetricsSink

__all__ = [
    "DomainError",
    "InMemoryMetricsSink",
    "OntologyContainer",
    "OntologyParseError",
    "QueryBinding",
    "RdfTriple",
    "RdfsClosureReasoner",
    "ReasoningSummary",
    "TriplePattern",
    "TriplePatternMatcher",
    "ValidationError",
    "XmlOntologyParser",
]
