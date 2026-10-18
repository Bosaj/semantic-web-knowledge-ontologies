"""
Semantic Web Knowledge Ontologies - Automated SPARQL Query Engine
Parses and queries OWL/RDF ontology files (tp1_library_cleaned.owl)
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class OntologyQueryEngine:
    def __init__(self, owl_file_path: str = "tp1_library_cleaned.owl"):
        self.owl_path = Path(owl_file_path)

    def execute_sparql(self, sparql_query: str) -> Dict[str, Any]:
        try:
            import rdflib

            g = rdflib.Graph()
            if not self.owl_path.exists():
                return {"status": "error", "message": f"OWL file '{self.owl_path}' not found."}

            g.parse(str(self.owl_path))
            results = g.query(sparql_query)

            bindings = []
            for row in results:
                row_dict = {}
                for var in results.vars:
                    val = row[var]
                    row_dict[str(var)] = str(val) if val is not None else None
                bindings.append(row_dict)

            return {
                "status": "success",
                "triples_count": len(g),
                "results_count": len(bindings),
                "bindings": bindings,
            }
        except ImportError:
            return {"status": "error", "message": "rdflib is not installed. Install with `pip install rdflib`."}
        except Exception as e:
            return {"status": "error", "message": str(e)}


if __name__ == "__main__":
    engine = OntologyQueryEngine()
    query = """
    SELECT ?subject ?predicate ?object
    WHERE {
        ?subject ?predicate ?object
    }
    LIMIT 5
    """
    res = engine.execute_sparql(query)
    print("SPARQL Query Execution Results:")
    print(json.dumps(res, indent=2))
