import importlib.util
import json
import sys
import tempfile
from pathlib import Path


def load_script_module(script_name):
    script_path = Path(__file__).resolve().parents[1] / "scripts" / script_name
    sys.path.insert(0, str(script_path.parent))
    spec = importlib.util.spec_from_file_location(script_name.replace(".py", ""), script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.path.pop(0)
    return module


def test_bridge_status_mapping_keeps_composition_gate_conservative():
    module = load_script_module("build_semantic_clustering.py")

    assert module.normalize_bridge_status({"approved_for_composition": "APPROVED"}) == "APPROVED"
    assert module.normalize_bridge_status({"approved_for_composition": "BLOCKED"}) == "BLOCKED"
    assert module.normalize_bridge_status({"approved_for_composition": "PENDING_REVIEW"}) == "DISCOVERED"
    assert module.normalize_bridge_status({"approved_for_composition": "CANDIDATE_NOT_APPROVED"}) == "DISCOVERED"


def test_audit_finding_helpers_emit_expected_severity():
    module = load_script_module("audit_semantic_clustering.py")

    high = module.high("missing_class", "ClassA", "Class missing")
    medium = module.medium("review_needed", "BridgeA", "Needs review")

    assert high["severity"] == "HIGH"
    assert high["category"] == "missing_class"
    assert medium["severity"] == "MEDIUM"
    assert medium["category"] == "review_needed"


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_minimal_workspace(route_method_id="M_CATALOG", property_cluster="C01", duplicate_route=False, bridge_status=None):
    root = Path(tempfile.mkdtemp(prefix="semantic_cluster_test_"))
    offline_root = root / "offline"
    clustering_dir = root / "clustering"

    write_json(offline_root / "01_database_inventory" / "tables.json", [{"table": "brands"}])
    write_json(offline_root / "01_database_inventory" / "columns.json", [{"column_id": "brands.brand_name"}])
    write_json(offline_root / "02_object_ontology" / "ontology_classes.json", {"classes": [{"class_id": "Brand", "source_table": "brands", "source_tables": ["brands"]}]})
    write_json(offline_root / "02_object_ontology" / "ontology_derived_classes.json", {"derived_classes": []})
    write_json(offline_root / "02_object_ontology" / "ontology_properties.json", {"properties": [{"property_id": "Brand.brandName", "class_id": "Brand", "source_column": "brands.brand_name"}]})
    write_json(offline_root / "02_object_ontology" / "ontology_relations.json", {"relations": []})
    write_json(offline_root / "02_object_ontology" / "ontology_class_methods.json", {"class_methods": []})
    write_json(
        offline_root / "02_object_ontology" / "ontology_method_candidates.json",
        {"method_candidates": [
            {"method_id": "M_CATALOG", "method_owner_class": "Brand", "target_classes": ["Brand"]},
            {"method_id": "M_OTHER", "method_owner_class": "Brand", "target_classes": ["Brand"]},
        ]},
    )
    write_json(offline_root / "03_business_task_ontology" / "business_intents.json", {"business_intents": [{"business_intent_id": "CatalogIntent"}]})
    write_json(offline_root / "03_business_task_ontology" / "task_scenarios.json", {"task_scenarios": [{"scenario_id": "S1", "expected_action": "EXECUTE_SQL", "method_id": "M_CATALOG"}]})
    write_json(offline_root / "04_method_contracts" / "method_contracts.json", {"method_contracts": []})
    write_json(offline_root / "05_semantic_policies" / "semantic_policies.json", {"semantic_policies": []})

    write_json(
        clustering_dir / "semantic_clusters.json",
        {"artifact": "semantic_clusters", "database_id": "db", "version": "v01", "clusters": [
            {"cluster_id": "C01", "included_base_classes": ["Brand"], "included_derived_classes": [], "key_properties": ["Brand.brandName"], "key_relations": [], "key_methods": ["M_CATALOG"], "served_business_intents": ["CatalogIntent"]},
            {"cluster_id": "C02", "included_base_classes": [], "included_derived_classes": [], "key_properties": [], "key_relations": [], "key_methods": ["M_OTHER"], "served_business_intents": []},
        ]},
    )
    write_json(
        clustering_dir / "cluster_memberships.json",
        {
            "artifact": "cluster_memberships",
            "database_id": "db",
            "version": "v01",
            "base_class_home": {"Brand": "C01"},
            "derived_class_home": {},
            "business_method_home": {"M_CATALOG": "C01", "M_OTHER": "C02"},
            "property_home": {"Brand.brandName": property_cluster},
            "relation_endpoint_homes": {},
            "context_memberships": {},
        },
    )
    bridges = []
    if bridge_status:
        bridges.append({"relation_id": "R1", "source_class": "Brand", "target_class": "Brand", "source_cluster": "C01", "target_cluster": "C01", "is_cross_cluster": False, "physical_join": {"left": "brands.brand_id", "right": "brands.brand_id", "join_type": "INNER"}, "composition_status": bridge_status})
        bridges.append(dict(bridges[0]))
    write_json(clustering_dir / "cluster_bridges.json", {"artifact": "cluster_bridges", "database_id": "db", "version": "v01", "bridges": bridges})
    routes = [{"scenario_id": "S1", "expected_action": "EXECUTE_SQL", "method_id": route_method_id, "target": "C01", "policy_route": None}]
    if duplicate_route:
        routes.append(dict(routes[0]))
    write_json(clustering_dir / "cluster_routing.json", {"artifact": "cluster_routing", "database_id": "db", "version": "v01", "intent_routes": [{"business_intent_id": "CatalogIntent", "candidate_clusters": ["C01"], "candidate_methods": ["M_CATALOG"]}], "scenario_routes": routes})

    return offline_root, clustering_dir


def test_wrong_scenario_method_is_detected():
    module = load_script_module("audit_semantic_clustering.py")
    offline_root, clustering_dir = build_minimal_workspace(route_method_id="M_OTHER")

    audit = module.audit_semantic_clustering("db", offline_root, clustering_dir)

    assert audit["readiness_status"] == "NOT_READY"
    assert any(item["category"] == "scenario_method_consistency" for item in audit["audit_findings"])


def test_wrong_property_home_is_detected():
    module = load_script_module("audit_semantic_clustering.py")
    offline_root, clustering_dir = build_minimal_workspace(property_cluster="C02")

    audit = module.audit_semantic_clustering("db", offline_root, clustering_dir)

    assert audit["readiness_status"] == "NOT_READY"
    assert any(item["category"] == "property_home_consistency" for item in audit["audit_findings"])


def test_duplicate_scenario_route_is_detected():
    module = load_script_module("audit_semantic_clustering.py")
    offline_root, clustering_dir = build_minimal_workspace(duplicate_route=True)

    audit = module.audit_semantic_clustering("db", offline_root, clustering_dir)

    assert audit["readiness_status"] == "NOT_READY"
    assert any(item["category"] == "duplicate_scenario_route_id" for item in audit["audit_findings"])
