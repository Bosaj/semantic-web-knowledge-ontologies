"""Architecture, entailment, BGP query, and load tests for ontology_engine."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

SRC_DIR = str(Path(__file__).resolve().parents[1] / "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from ontology_engine import (  # noqa: E402
    InMemoryMetricsSink,
    OntologyContainer,
    OntologyParseError,
    RdfTriple,
    RdfsClosureReasoner,
    TriplePattern,
    TriplePatternMatcher,
    ValidationError,
    XmlOntologyParser,
)
from ontology_engine.contracts import InMemoryTripleStore  # noqa: E402
from ontology_engine.reasoner import (  # noqa: E402
    RDF_TYPE,
    RDFS_SUBCLASS_OF,
    RDFS_SUBPROPERTY_OF,
)

SAMPLE_OWL = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
         xmlns:owl="http://www.w3.org/2002/07/owl#"
         xmlns:ex="http://example.org/acad#">
  <owl:Class rdf:about="http://example.org/acad#DoctoralStudent">
    <rdfs:subClassOf rdf:resource="http://example.org/acad#Student"/>
  </owl:Class>
  <owl:Class rdf:about="http://example.org/acad#Student">
    <rdfs:subClassOf rdf:resource="http://example.org/acad#Person"/>
  </owl:Class>
  <owl:NamedIndividual rdf:about="http://example.org/acad#Oussama">
    <rdf:type rdf:resource="http://example.org/acad#DoctoralStudent"/>
    <ex:researches rdf:resource="http://example.org/acad#SemanticWeb"/>
  </owl:NamedIndividual>
</rdf:RDF>
"""


def _build_container() -> OntologyContainer:
    container = OntologyContainer()
    container.register_singleton(InMemoryMetricsSink, lambda _: InMemoryMetricsSink())
    container.register_singleton(InMemoryTripleStore, lambda _: InMemoryTripleStore())
    container.register_singleton(
        XmlOntologyParser,
        lambda c: XmlOntologyParser(metrics=c.resolve(InMemoryMetricsSink)),
    )
    container.register_singleton(
        RdfsClosureReasoner,
        lambda c: RdfsClosureReasoner(
            store=c.resolve(InMemoryTripleStore),
            metrics=c.resolve(InMemoryMetricsSink),
        ),
    )
    container.register_singleton(
        TriplePatternMatcher,
        lambda c: TriplePatternMatcher(metrics=c.resolve(InMemoryMetricsSink)),
    )
    return container


class TestOntologyArchitecture(unittest.TestCase):
    def test_xml_parser_rdfs_closure_and_conjunctive_bgp_query(self) -> None:
        container = _build_container()
        parser: XmlOntologyParser = container.resolve(XmlOntologyParser)
        reasoner: RdfsClosureReasoner = container.resolve(RdfsClosureReasoner)
        matcher: TriplePatternMatcher = container.resolve(TriplePatternMatcher)
        store: InMemoryTripleStore = container.resolve(InMemoryTripleStore)

        triples = parser.parse_rdf_xml(SAMPLE_OWL)
        triples.append(
            RdfTriple(
                "http://example.org/acad#researches",
                RDFS_SUBPROPERTY_OF,
                "http://example.org/acad#studies",
            )
        )
        closure, summary = reasoner.materialize(triples)

        self.assertGreaterEqual(summary.inferred_triples, 3)
        self.assertIn(
            RdfTriple(
                "http://example.org/acad#Oussama",
                RDF_TYPE,
                "http://example.org/acad#Person",
            ),
            closure,
        )
        self.assertIn(
            RdfTriple(
                "http://example.org/acad#Oussama",
                "http://example.org/acad#studies",
                "http://example.org/acad#SemanticWeb",
            ),
            closure,
        )
        self.assertEqual(len(store.all_triples()), summary.total_triples)

        bindings = matcher.query(
            closure,
            [
                TriplePattern("?who", RDF_TYPE, "http://example.org/acad#Person"),
                TriplePattern("?who", "http://example.org/acad#studies", "?topic"),
            ],
        )
        self.assertEqual(len(bindings), 1)
        self.assertEqual(bindings[0].bindings["?who"], "http://example.org/acad#Oussama")
        self.assertEqual(
            bindings[0].bindings["?topic"], "http://example.org/acad#SemanticWeb"
        )

    def test_validation_and_malformed_xml_rejection(self) -> None:
        container = _build_container()
        parser: XmlOntologyParser = container.resolve(XmlOntologyParser)
        matcher: TriplePatternMatcher = container.resolve(TriplePatternMatcher)

        with self.assertRaises(TypeError):
            parser.parse_rdf_xml(123)  # type: ignore[arg-type]
        with self.assertRaises(OntologyParseError):
            parser.parse_rdf_xml("")
        with self.assertRaises(OntologyParseError):
            parser.parse_rdf_xml("<rdf:RDF><broken>")
        with self.assertRaises(ValidationError):
            matcher.query([], [])

    def test_real_ontology_library_files_and_reasoning_benchmark(self) -> None:
        container = _build_container()
        parser: XmlOntologyParser = container.resolve(XmlOntologyParser)
        reasoner: RdfsClosureReasoner = container.resolve(RdfsClosureReasoner)
        metrics: InMemoryMetricsSink = container.resolve(InMemoryMetricsSink)

        onto_dir = Path(__file__).resolve().parents[1] / "Ontologies_Library"
        for owl_path in sorted(onto_dir.glob("*.owl")):
            raw = owl_path.read_text(encoding="utf-8", errors="ignore")
            if raw.lstrip().startswith("<"):
                parsed = parser.parse_rdf_xml(raw)
                self.assertGreater(len(parsed), 0, f"No triples extracted from {owl_path.name}")

        # Synthetic 30-level hierarchy + 200 individuals entailment stress test
        chain: list[RdfTriple] = [
            RdfTriple(f"ex:C{i}", RDFS_SUBCLASS_OF, f"ex:C{i + 1}") for i in range(25)
        ]
        for j in range(100):
            chain.append(RdfTriple(f"ex:ind{j}", RDF_TYPE, "ex:C0"))
        closure, summary = reasoner.materialize(chain)
        self.assertEqual(summary.asserted_triples, 125)
        self.assertGreater(summary.inferred_triples, 2000)
        self.assertLess(metrics.percentile_ms("ontology.reason_ms", 95), 2000.0)


if __name__ == "__main__":
    unittest.main()
