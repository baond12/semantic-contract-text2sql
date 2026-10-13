from pathlib import Path
from typing import Any

from semantic_contract_text2sql.io import load_json


ARTIFACT_FILENAMES = {
    "classes": "ontology_classes.json",
    "properties": "ontology_properties.json",
    "relations": "ontology_relations.json",
    "methods": "ontology_methods.json",
    "intent_rules": "intent_method_rules.json",
    "sql_templates": "sql_templates.json",
    "unsupported_scope": "unsupported_scope.json",
    "runtime_config": "ontology_runtime_config.json",
}


def load_ontology_artifacts(ontology_root: str | Path) -> dict[str, Any]:
    ontology_root = Path(ontology_root)
    return {
        name: load_json(ontology_root / filename)
        for name, filename in ARTIFACT_FILENAMES.items()
    }

