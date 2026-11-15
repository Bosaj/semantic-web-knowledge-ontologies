"""Pure-Python RDF/XML parser, RDFS fixpoint reasoner, and BGP matcher."""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Sequence

from .contracts import (
    MetricsSink,
    OntologyParseError,
    QueryBinding,
    RdfTriple,
    ReasoningSummary,
    TriplePattern,
    TripleStoreProtocol,
    ValidationError,
)
from .telemetry import InMemoryMetricsSink

RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS_NS = "http://www.w3.org/2000/01/rdf-schema#"
OWL_NS = "http://www.w3.org/2002/07/owl#"

RDF_TYPE = f"{RDF_NS}type"
RDFS_SUBCLASS_OF = f"{RDFS_NS}subClassOf"
RDFS_SUBPROPERTY_OF = f"{RDFS_NS}subPropertyOf"


class XmlOntologyParser:
    """Extracts core RDF/OWL class, hierarchy, property, and individual triples."""

    def __init__(self, metrics: MetricsSink | None = None) -> None:
        self._metrics = metrics or InMemoryMetricsSink()

    def parse_rdf_xml(self, xml_text: str) -> list[RdfTriple]:
        started = time.perf_counter()
        if not isinstance(xml_text, str):
            raise TypeError("xml_text must be a string")
        if not xml_text.strip():
            raise OntologyParseError("RDF/XML payload is empty")
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            raise OntologyParseError(f"Malformed XML ontology: {exc}") from exc

        triples: list[RdfTriple] = []
        rdf_about = f"{{{RDF_NS}}}about"
        rdf_id = f"{{{RDF_NS}}}ID"
        rdf_resource = f"{{{RDF_NS}}}resource"

        for elem in root:
            subject = elem.attrib.get(rdf_about) or elem.attrib.get(rdf_id)
            if not subject:
                continue
            tag_iri = self._tag_to_iri(elem.tag)
            triples.append(RdfTriple(subject, RDF_TYPE, tag_iri))
            for child in elem:
                pred_iri = self._tag_to_iri(child.tag)
                obj = child.attrib.get(rdf_resource)
                if obj is None:
                    text_val = (child.text or "").strip()
                    if text_val:
                        obj = f'"{text_val}"'
                if obj:
                    triples.append(RdfTriple(subject, pred_iri, obj))

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        self._metrics.increment("ontology.parsed_docs")
        self._metrics.observe_ms("ontology.parse_ms", elapsed_ms)
        return triples

    @staticmethod
    def _tag_to_iri(tag: str) -> str:
        if tag.startswith("{") and "}" in tag:
            ns, local = tag[1:].split("}", 1)
            return f"{ns}{local}"
        return tag


class RdfsClosureReasoner:
    """Fixpoint RDFS reasoner supporting subClassOf, subPropertyOf, and rdf:type rules."""

    def __init__(
        self,
        store: TripleStoreProtocol | None = None,
        metrics: MetricsSink | None = None,
    ) -> None:
        self._store = store
        self._metrics = metrics or InMemoryMetricsSink()

    def materialize(
        self, triples: Iterable[RdfTriple], max_iterations: int = 128
    ) -> tuple[set[RdfTriple], ReasoningSummary]:
        started = time.perf_counter()
        if max_iterations <= 0:
            raise ValidationError("max_iterations must be positive")

        asserted = set(triples)
        closure = set(asserted)
        iterations = 0

        for _ in range(max_iterations):
            iterations += 1
            subclasses: dict[str, set[str]] = {}
            subprops: dict[str, set[str]] = {}

            for t in closure:
                if t.predicate == RDFS_SUBCLASS_OF:
                    subclasses.setdefault(t.subject, set()).add(t.obj)
                elif t.predicate == RDFS_SUBPROPERTY_OF:
                    subprops.setdefault(t.subject, set()).add(t.obj)

            new_triples: set[RdfTriple] = set()
            for t in closure:
                # rdfs11: (A subClassOf B) & (B subClassOf C) => (A subClassOf C)
                if t.predicate == RDFS_SUBCLASS_OF:
                    for super_cls in subclasses.get(t.obj, ()):
                        cand = RdfTriple(t.subject, RDFS_SUBCLASS_OF, super_cls)
                        if cand not in closure:
                            new_triples.add(cand)
                # rdfs9: (x rdf:type A) & (A subClassOf B) => (x rdf:type B)
                elif t.predicate == RDF_TYPE:
                    for super_cls in subclasses.get(t.obj, ()):
                        cand = RdfTriple(t.subject, RDF_TYPE, super_cls)
                        if cand not in closure:
                            new_triples.add(cand)
                # rdfs7 & rdfs5: subPropertyOf hierarchy + property entailment
                elif t.predicate == RDFS_SUBPROPERTY_OF:
                    for super_prop in subprops.get(t.obj, ()):
                        cand = RdfTriple(t.subject, RDFS_SUBPROPERTY_OF, super_prop)
                        if cand not in closure:
                            new_triples.add(cand)
                if t.predicate in subprops:
                    for super_prop in subprops[t.predicate]:
                        cand = RdfTriple(t.subject, super_prop, t.obj)
                        if cand not in closure:
                            new_triples.add(cand)

            if not new_triples:
                break
            closure.update(new_triples)

        if self._store is not None:
            self._store.add_all(list(closure))

        summary = ReasoningSummary(
            asserted_triples=len(asserted),
            inferred_triples=len(closure) - len(asserted),
            total_triples=len(closure),
            iterations=iterations,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        self._metrics.increment("ontology.reasoning_runs")
        self._metrics.observe_ms("ontology.reason_ms", elapsed_ms)
        return closure, summary


class TriplePatternMatcher:
    """Evaluates conjunctive SPARQL-like triple patterns with deterministic joins."""

    def __init__(self, metrics: MetricsSink | None = None) -> None:
        self._metrics = metrics or InMemoryMetricsSink()

    def query(
        self,
        triples: Iterable[RdfTriple],
        patterns: Sequence[TriplePattern],
        limit: int | None = None,
    ) -> list[QueryBinding]:
        started = time.perf_counter()
        if not patterns:
            raise ValidationError("patterns cannot be empty")
        if limit is not None and (
            not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0
        ):
            raise ValidationError("limit must be a positive integer")

        triple_list = sorted(
            set(triples), key=lambda t: (t.subject, t.predicate, t.obj)
        )
        solutions: list[dict[str, str]] = [{}]

        for pattern in patterns:
            next_solutions: list[dict[str, str]] = []
            for env in solutions:
                for triple in triple_list:
                    merged = self._match_pattern(pattern, triple, env)
                    if merged is not None:
                        next_solutions.append(merged)
            solutions = next_solutions
            if not solutions:
                break

        if limit is not None:
            solutions = solutions[:limit]

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        self._metrics.increment("ontology.queries")
        self._metrics.observe_ms("ontology.query_ms", elapsed_ms)
        return [QueryBinding(bindings=env) for env in solutions]

    @staticmethod
    def _match_pattern(
        pattern: TriplePattern, triple: RdfTriple, env: dict[str, str]
    ) -> dict[str, str] | None:
        updated = dict(env)
        pairs = (
            (pattern.subject, triple.subject),
            (pattern.predicate, triple.predicate),
            (pattern.obj, triple.obj),
        )
        for pat_term, actual_term in pairs:
            if pat_term.startswith("?"):
                bound = updated.get(pat_term)
                if bound is None:
                    updated[pat_term] = actual_term
                elif bound != actual_term:
                    return None
            elif pat_term != actual_term:
                return None
        return updated
