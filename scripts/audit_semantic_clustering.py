import argparse
import json
from collections import Counter
from pathlib import Path


ALLOWED_BRIDGE_STATUSES = {"DISCOVERED", "VALIDATED", "APPROVED", "BLOCKED"}
ALLOWED_LEGACY_APPROVALS = {"PENDING_REVIEW", "CANDIDATE_NOT_APPROVED", "APPROVED", "BLOCKED"}


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_json(data, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def high(category, owner_id, message, evidence=None):
    return {
        "severity": "HIGH",
        "category": category,
        "owner_id": owner_id,
        "message": message,
        "evidence": evidence or {},
    }


def medium(category, owner_id, message, evidence=None):
    return {
        "severity": "MEDIUM",
        "category": category,
        "owner_id": owner_id,
        "message": message,
        "evidence": evidence or {},
    }


def load_upstream(offline_root):
    root = Path(offline_root)
    return {
        "tables": load_json(root / "01_database_inventory" / "tables.json"),
        "columns": load_json(root / "01_database_inventory" / "columns.json"),
        "classes": load_json(root / "02_object_ontology" / "ontology_classes.json")["classes"],
        "derived_classes": load_json(root / "02_object_ontology" / "ontology_derived_classes.json")["derived_classes"],
        "properties": load_json(root / "02_object_ontology" / "ontology_properties.json")["properties"],
        "relations": load_json(root / "02_object_ontology" / "ontology_relations.json")["relations"],
        "class_methods": load_json(root / "02_object_ontology" / "ontology_class_methods.json")["class_methods"],
        "business_methods": load_json(root / "02_object_ontology" / "ontology_method_candidates.json")["method_candidates"],
        "business_intents": load_json(root / "03_business_task_ontology" / "business_intents.json")["business_intents"],
        "task_scenarios": load_json(root / "03_business_task_ontology" / "task_scenarios.json")["task_scenarios"],
        "method_contracts": load_json(root / "04_method_contracts" / "method_contracts.json")["method_contracts"],
        "semantic_policies": load_json(root / "05_semantic_policies" / "semantic_policies.json")["semantic_policies"],
    }


def load_clustering(clustering_dir):
    root = Path(clustering_dir)
    coverage_path = root / "cluster_coverage_audit.json"
    coverage_audit = {}
    if coverage_path.exists():
        coverage_audit = load_json(coverage_path)
    contracts_path = root / "cluster_artifact_contracts.json"
    artifact_contracts = {}
    if contracts_path.exists():
        artifact_contracts = load_json(contracts_path)
    return {
        "semantic_clusters": load_json(root / "semantic_clusters.json"),
        "cluster_memberships": load_json(root / "cluster_memberships.json"),
        "cluster_bridges": load_json(root / "cluster_bridges.json"),
        "cluster_routing": load_json(root / "cluster_routing.json"),
        "cluster_coverage_audit": coverage_audit,
        "cluster_artifact_contracts": artifact_contracts,
    }


def id_set(items, key):
    return {item[key] for item in items}


def compare_exact_set(findings, category, owner_id, expected, actual):
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing:
        findings.append(high(category + "_missing", owner_id, "Missing required ids.", {"missing": missing}))
    if extra:
        findings.append(high(category + "_extra", owner_id, "Unknown ids found.", {"extra": extra}))


def add_duplicate_findings(findings, category, owner_id, values):
    counts = Counter(values)
    duplicates = sorted([value for value, count in counts.items() if value and count > 1])
    if duplicates:
        findings.append(high(category, owner_id, "Duplicate ids found.", {"duplicates": duplicates}))


def audit_memberships(upstream, clustering, cluster_ids):
    findings = []
    memberships = clustering["cluster_memberships"]

    expected_base = id_set(upstream["classes"], "class_id")
    expected_derived = id_set(upstream["derived_classes"], "class_id")
    expected_properties = id_set(upstream["properties"], "property_id")
    expected_methods = id_set(upstream["business_methods"], "method_id")

    actual_base = set(memberships.get("base_class_home", {}))
    actual_derived = set(memberships.get("derived_class_home", {}))
    actual_properties = set(memberships.get("property_home", {}))
    actual_methods = set(memberships.get("business_method_home", {}))

    compare_exact_set(findings, "base_class_membership", "cluster_memberships.base_class_home", expected_base, actual_base)
    compare_exact_set(findings, "derived_class_membership", "cluster_memberships.derived_class_home", expected_derived, actual_derived)
    compare_exact_set(findings, "property_membership", "cluster_memberships.property_home", expected_properties, actual_properties)
    compare_exact_set(findings, "business_method_membership", "cluster_memberships.business_method_home", expected_methods, actual_methods)

    for section in ["base_class_home", "derived_class_home", "property_home", "business_method_home"]:
        for item_id, cluster_id in memberships.get(section, {}).items():
            if cluster_id not in cluster_ids:
                findings.append(high("membership_unknown_cluster", item_id, f"{section} references unknown cluster.", {"cluster_id": cluster_id}))

    class_home = {
        **memberships.get("base_class_home", {}),
        **memberships.get("derived_class_home", {}),
    }
    properties_by_id = {item["property_id"]: item for item in upstream["properties"]}
    for property_id, cluster_id in memberships.get("property_home", {}).items():
        prop = properties_by_id.get(property_id)
        if not prop:
            continue
        expected_cluster = class_home.get(prop.get("class_id"))
        if cluster_id != expected_cluster:
            findings.append(
                high(
                    "property_home_consistency",
                    property_id,
                    "Property home must match its owner class primary cluster.",
                    {"actual_cluster": cluster_id, "expected_cluster": expected_cluster, "owner_class": prop.get("class_id")},
                )
            )

    known_class_ids = expected_base | expected_derived
    for cluster_id, items in memberships.get("context_memberships", {}).items():
        if cluster_id not in cluster_ids:
            findings.append(high("context_membership_unknown_cluster", cluster_id, "Context membership references unknown cluster."))
        for item_id in items:
            if item_id not in known_class_ids:
                findings.append(medium("context_membership_unknown_class", cluster_id, "Context dependency is not a known class.", {"class_id": item_id}))

    return findings


def audit_clusters(upstream, clustering, cluster_ids):
    findings = []
    memberships = clustering["cluster_memberships"]
    expected_base_members_by_cluster = {}
    for class_id, cluster_id in memberships.get("base_class_home", {}).items():
        expected_base_members_by_cluster.setdefault(cluster_id, set()).add(class_id)
    expected_derived_members_by_cluster = {}
    for class_id, cluster_id in memberships.get("derived_class_home", {}).items():
        expected_derived_members_by_cluster.setdefault(cluster_id, set()).add(class_id)
    expected_method_members_by_cluster = {}
    for method_id, cluster_id in memberships.get("business_method_home", {}).items():
        expected_method_members_by_cluster.setdefault(cluster_id, set()).add(method_id)

    expected_base = id_set(upstream["classes"], "class_id")
    expected_derived = id_set(upstream["derived_classes"], "class_id")
    expected_properties = id_set(upstream["properties"], "property_id")
    expected_relations = id_set(upstream["relations"], "relation_id")
    expected_methods = id_set(upstream["business_methods"], "method_id")
    expected_intents = id_set(upstream["business_intents"], "business_intent_id")

    for cluster in clustering["semantic_clusters"].get("clusters", []):
        cluster_id = cluster.get("cluster_id")
        if cluster_id not in cluster_ids:
            findings.append(high("cluster_unknown_id", cluster_id, "Cluster id is not registered."))
        for class_id in cluster.get("included_base_classes", []):
            if class_id not in expected_base:
                findings.append(high("cluster_unknown_base_class", cluster_id, "Cluster includes unknown base class.", {"class_id": class_id}))
        for class_id in cluster.get("included_derived_classes", []):
            if class_id not in expected_derived:
                findings.append(high("cluster_unknown_derived_class", cluster_id, "Cluster includes unknown derived class.", {"class_id": class_id}))
        for prop_id in cluster.get("key_properties", []):
            if prop_id not in expected_properties:
                findings.append(medium("cluster_unknown_key_property", cluster_id, "Cluster key property is not known.", {"property_id": prop_id}))
        for relation_id in cluster.get("key_relations", []):
            if relation_id not in expected_relations:
                findings.append(medium("cluster_unknown_key_relation", cluster_id, "Cluster key relation is not known.", {"relation_id": relation_id}))
        for method_id in cluster.get("key_methods", []):
            if method_id not in expected_methods:
                findings.append(high("cluster_unknown_key_method", cluster_id, "Cluster key method is not known.", {"method_id": method_id}))
        for intent_id in cluster.get("served_business_intents", []):
            if intent_id not in expected_intents:
                findings.append(medium("cluster_unknown_business_intent", cluster_id, "Cluster served intent is not known.", {"business_intent_id": intent_id}))

        actual_base = set(cluster.get("included_base_classes", []))
        expected_base_for_cluster = expected_base_members_by_cluster.get(cluster_id, set())
        if actual_base != expected_base_for_cluster:
            findings.append(
                high(
                    "cluster_base_membership_consistency",
                    cluster_id,
                    "Cluster included_base_classes must match base_class_home inverse mapping.",
                    {"actual": sorted(actual_base), "expected": sorted(expected_base_for_cluster)},
                )
            )

        actual_derived = set(cluster.get("included_derived_classes", []))
        expected_derived_for_cluster = expected_derived_members_by_cluster.get(cluster_id, set())
        if actual_derived != expected_derived_for_cluster:
            findings.append(
                high(
                    "cluster_derived_membership_consistency",
                    cluster_id,
                    "Cluster included_derived_classes must match derived_class_home inverse mapping.",
                    {"actual": sorted(actual_derived), "expected": sorted(expected_derived_for_cluster)},
                )
            )

        actual_methods = set(cluster.get("key_methods", []))
        expected_methods_for_cluster = expected_method_members_by_cluster.get(cluster_id, set())
        if actual_methods != expected_methods_for_cluster:
            findings.append(
                high(
                    "cluster_method_membership_consistency",
                    cluster_id,
                    "Cluster key_methods must match business_method_home inverse mapping.",
                    {"actual": sorted(actual_methods), "expected": sorted(expected_methods_for_cluster)},
                )
            )

    return findings


def audit_derived_classes(upstream):
    findings = []
    base_class_ids = id_set(upstream["classes"], "class_id")
    for item in upstream["derived_classes"]:
        source_classes = item.get("source_classes", [])
        if len(source_classes) > 2:
            findings.append(high("derived_class_too_wide", item["class_id"], "Derived class must use at most two base classes.", {"source_classes": source_classes}))
        for class_id in source_classes:
            if class_id not in base_class_ids:
                findings.append(high("derived_class_unknown_source_class", item["class_id"], "Derived class source class is not a base class.", {"source_class": class_id}))
    return findings


def audit_bridges(upstream, clustering, cluster_ids):
    findings = []
    memberships = clustering["cluster_memberships"]
    base_home = memberships.get("base_class_home", {})
    derived_home = memberships.get("derived_class_home", {})
    class_home = {**base_home, **derived_home}
    relations_by_id = {item["relation_id"]: item for item in upstream["relations"]}
    expected_relations = set(relations_by_id)
    bridges = clustering["cluster_bridges"].get("bridges", [])
    add_duplicate_findings(findings, "duplicate_bridge_relation_id", "cluster_bridges.bridges", [item.get("relation_id") for item in bridges])
    bridge_ids = {item.get("relation_id") for item in bridges}

    compare_exact_set(findings, "bridge_relation_coverage", "cluster_bridges.bridges", expected_relations, bridge_ids)

    for bridge in bridges:
        relation_id = bridge.get("relation_id")
        relation = relations_by_id.get(relation_id)
        if not relation:
            continue

        if bridge.get("source_class") != relation.get("source_class"):
            findings.append(high("bridge_source_class_mismatch", relation_id, "Bridge source class does not match ontology relation.", {"bridge": bridge.get("source_class"), "relation": relation.get("source_class")}))
        if bridge.get("target_class") != relation.get("target_class"):
            findings.append(high("bridge_target_class_mismatch", relation_id, "Bridge target class does not match ontology relation.", {"bridge": bridge.get("target_class"), "relation": relation.get("target_class")}))
        if bridge.get("source_cluster") != class_home.get(relation.get("source_class")):
            findings.append(high("bridge_source_cluster_mismatch", relation_id, "Bridge source cluster does not match class membership."))
        if bridge.get("target_cluster") != class_home.get(relation.get("target_class")):
            findings.append(high("bridge_target_cluster_mismatch", relation_id, "Bridge target cluster does not match class membership."))
        if bridge.get("source_cluster") not in cluster_ids:
            findings.append(high("bridge_unknown_source_cluster", relation_id, "Bridge source cluster is unknown."))
        if bridge.get("target_cluster") not in cluster_ids:
            findings.append(high("bridge_unknown_target_cluster", relation_id, "Bridge target cluster is unknown."))

        physical_join = bridge.get("physical_join", {})
        mapping = relation.get("database_mapping", {})
        if physical_join.get("left") != mapping.get("left") or physical_join.get("right") != mapping.get("right"):
            findings.append(high("bridge_physical_join_mismatch", relation_id, "Bridge physical join does not match ontology relation mapping.", {"bridge": physical_join, "relation": mapping}))
        if physical_join.get("join_type") != mapping.get("join_type"):
            findings.append(high("bridge_join_type_mismatch", relation_id, "Bridge join type does not match ontology relation mapping.", {"bridge": physical_join.get("join_type"), "relation": mapping.get("join_type")}))

        composition_status = bridge.get("composition_status")
        if not composition_status:
            findings.append(high("bridge_missing_composition_status", relation_id, "Bridge must explicitly declare composition_status."))
        elif composition_status not in ALLOWED_BRIDGE_STATUSES:
            findings.append(high("bridge_invalid_composition_status", relation_id, "Invalid bridge composition_status.", {"composition_status": composition_status}))
        if bridge.get("approved_for_composition") and bridge["approved_for_composition"] not in ALLOWED_LEGACY_APPROVALS:
            findings.append(medium("bridge_unknown_legacy_approval", relation_id, "Unknown legacy approved_for_composition value.", {"approved_for_composition": bridge["approved_for_composition"]}))
        if bridge.get("approved_for_composition") == "CANDIDATE_NOT_APPROVED" and composition_status == "APPROVED":
            findings.append(high("bridge_composition_contradiction", relation_id, "Bridge cannot be APPROVED when legacy approval says CANDIDATE_NOT_APPROVED."))

    endpoint_homes = memberships.get("relation_endpoint_homes", {})
    compare_exact_set(findings, "relation_endpoint_home_coverage", "cluster_memberships.relation_endpoint_homes", expected_relations, set(endpoint_homes))
    for relation_id, endpoints in endpoint_homes.items():
        relation = relations_by_id.get(relation_id)
        if not relation:
            continue
        expected = [
            class_home.get(relation.get("source_class")),
            class_home.get(relation.get("target_class")),
        ]
        if endpoints != expected:
            findings.append(
                high(
                    "bridge_endpoint_consistency",
                    relation_id,
                    "relation_endpoint_homes must match source/target class homes.",
                    {"actual": endpoints, "expected": expected},
                )
            )

    return findings


def audit_routing(upstream, clustering, cluster_ids):
    findings = []
    routing = clustering["cluster_routing"]
    intent_ids = id_set(upstream["business_intents"], "business_intent_id")
    method_ids = id_set(upstream["business_methods"], "method_id")
    scenario_by_id = {item["scenario_id"]: item for item in upstream["task_scenarios"]}
    scenario_ids = set(scenario_by_id)
    policy_actions = {"CLARIFY", "REFUSE", "UNSUPPORTED"}

    route_intent_ids = {item.get("business_intent_id") for item in routing.get("intent_routes", [])}
    compare_exact_set(findings, "intent_route_coverage", "cluster_routing.intent_routes", intent_ids, route_intent_ids)

    for route in routing.get("intent_routes", []):
        for cluster_id in route.get("candidate_clusters", []):
            if cluster_id not in cluster_ids:
                findings.append(high("intent_route_unknown_cluster", route.get("business_intent_id"), "Intent route references unknown cluster.", {"cluster_id": cluster_id}))
        for method_id in route.get("candidate_methods", []):
            if method_id not in method_ids:
                findings.append(high("intent_route_unknown_method", route.get("business_intent_id"), "Intent route references unknown method.", {"method_id": method_id}))

    scenario_routes = routing.get("scenario_routes", [])
    add_duplicate_findings(findings, "duplicate_scenario_route_id", "cluster_routing.scenario_routes", [item.get("scenario_id") for item in scenario_routes])
    add_duplicate_findings(findings, "duplicate_intent_route_id", "cluster_routing.intent_routes", [item.get("business_intent_id") for item in routing.get("intent_routes", [])])
    route_scenario_ids = {item.get("scenario_id") for item in scenario_routes}
    compare_exact_set(findings, "scenario_route_coverage", "cluster_routing.scenario_routes", scenario_ids, route_scenario_ids)

    for route in scenario_routes:
        scenario_id = route.get("scenario_id")
        scenario = scenario_by_id.get(scenario_id)
        if not scenario:
            continue
        expected_action = scenario.get("expected_action")
        if route.get("expected_action") != expected_action:
            findings.append(high("scenario_route_action_mismatch", scenario_id, "Scenario route expected_action does not match task scenario.", {"route": route.get("expected_action"), "scenario": expected_action}))

        if route.get("method_id") != scenario.get("method_id") and expected_action == "EXECUTE_SQL":
            findings.append(
                high(
                    "scenario_method_consistency",
                    scenario_id,
                    "Scenario route method_id must match upstream task scenario method_id.",
                    {"route_method_id": route.get("method_id"), "scenario_method_id": scenario.get("method_id")},
                )
            )

        if expected_action == "EXECUTE_SQL":
            if route.get("method_id") not in method_ids:
                findings.append(high("execute_route_missing_method", scenario_id, "EXECUTE_SQL scenario must route to a known method.", {"method_id": route.get("method_id")}))
            if route.get("target") not in cluster_ids:
                findings.append(high("execute_route_unknown_cluster", scenario_id, "EXECUTE_SQL scenario must route to a known cluster.", {"target": route.get("target")}))
            expected_target = clustering["cluster_memberships"].get("business_method_home", {}).get(route.get("method_id"))
            if route.get("target") != expected_target:
                findings.append(
                    high(
                        "scenario_target_consistency",
                        scenario_id,
                        "Scenario route target must match business method home cluster.",
                        {"actual_target": route.get("target"), "expected_target": expected_target, "method_id": route.get("method_id")},
                    )
                )
        if expected_action in policy_actions:
            if route.get("method_id"):
                findings.append(high("policy_route_has_method", scenario_id, "Policy action must not route to SQL method.", {"method_id": route.get("method_id")}))
            if route.get("target") != "POLICY_GATE":
                findings.append(high("policy_route_not_policy_gate", scenario_id, "Policy action must target POLICY_GATE.", {"target": route.get("target")}))

    return findings


def audit_artifact_contracts(clustering):
    findings = []
    contracts = clustering.get("cluster_artifact_contracts", {})
    if not contracts:
        return findings

    contract_map = contracts.get("contracts", {})
    artifact_to_payload = {
        "semantic_clusters.json": clustering["semantic_clusters"],
        "cluster_memberships.json": clustering["cluster_memberships"],
        "cluster_bridges.json": clustering["cluster_bridges"],
        "cluster_routing.json": clustering["cluster_routing"],
        "cluster_coverage_audit.json": clustering.get("cluster_coverage_audit", {}),
    }

    for artifact_name, schema in contract_map.items():
        payload = artifact_to_payload.get(artifact_name)
        if not payload:
            continue
        for field in schema.get("required", []):
            if field not in payload:
                findings.append(high("json_schema_required_field_missing", artifact_name, "Artifact is missing a required top-level field from cluster_artifact_contracts.", {"field": field}))

    return findings


def build_coverage_summary(upstream, clustering):
    memberships = clustering["cluster_memberships"]
    routing = clustering["cluster_routing"]
    bridges = clustering["cluster_bridges"].get("bridges", [])

    return {
        "base_classes": {"total": len(upstream["classes"]), "assigned": len(memberships.get("base_class_home", {}))},
        "derived_classes": {"total": len(upstream["derived_classes"]), "assigned": len(memberships.get("derived_class_home", {}))},
        "properties": {"total": len(upstream["properties"]), "assigned": len(memberships.get("property_home", {}))},
        "relations": {
            "total": len(upstream["relations"]),
            "mapped": len(bridges),
            "cross_cluster": len([item for item in bridges if item.get("is_cross_cluster")]),
        },
        "class_methods": len(upstream["class_methods"]),
        "business_methods": {"total": len(upstream["business_methods"]), "assigned": len(memberships.get("business_method_home", {}))},
        "scenarios": {
            "total": len(upstream["task_scenarios"]),
            "routed": len(routing.get("scenario_routes", [])),
            "action_distribution": dict(Counter(item.get("expected_action") for item in upstream["task_scenarios"])),
        },
    }


def audit_semantic_clustering(database_id, offline_root, clustering_dir):
    upstream = load_upstream(offline_root)
    clustering = load_clustering(clustering_dir)
    clusters = clustering["semantic_clusters"].get("clusters", [])
    cluster_ids = {item.get("cluster_id") for item in clusters}

    findings = []
    for artifact_name, artifact in clustering.items():
        if not artifact:
            continue
        if artifact.get("database_id") != database_id:
            findings.append(high("database_id_mismatch", artifact_name, "Artifact database_id does not match requested database_id.", {"artifact_database_id": artifact.get("database_id")}))

    if len(cluster_ids) != len(clusters):
        findings.append(high("duplicate_cluster_id", "semantic_clusters", "Duplicate cluster_id found."))

    findings.extend(audit_memberships(upstream, clustering, cluster_ids))
    findings.extend(audit_clusters(upstream, clustering, cluster_ids))
    findings.extend(audit_derived_classes(upstream))
    findings.extend(audit_bridges(upstream, clustering, cluster_ids))
    findings.extend(audit_routing(upstream, clustering, cluster_ids))
    findings.extend(audit_artifact_contracts(clustering))

    high_findings = [item for item in findings if item["severity"] == "HIGH"]
    medium_findings = [item for item in findings if item["severity"] == "MEDIUM"]
    readiness_status = "READY" if not high_findings else "NOT_READY"

    return {
        "database_id": database_id,
        "artifact_type": "semantic_clustering_audit",
        "version": "v01",
        "readiness_status": readiness_status,
        "coverage_summary": build_coverage_summary(upstream, clustering),
        "finding_count": len(findings),
        "high_findings": len(high_findings),
        "medium_findings": len(medium_findings),
        "finding_count_by_category": dict(Counter(item["category"] for item in findings)),
        "audit_findings": findings,
    }


def build_parser():
    parser = argparse.ArgumentParser(description="Audit semantic clustering artifacts against upstream offline artifacts.")
    parser.add_argument("--database-id", required=True)
    parser.add_argument("--offline-root", required=True)
    parser.add_argument("--clustering-dir", required=True)
    parser.add_argument("--output-path")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    audit = audit_semantic_clustering(
        database_id=args.database_id,
        offline_root=Path(args.offline_root),
        clustering_dir=Path(args.clustering_dir),
    )

    if args.output_path:
        save_json(audit, args.output_path)

    printable = {key: value for key, value in audit.items() if key != "audit_findings"}
    print(json.dumps(printable, ensure_ascii=False, indent=2))

    if audit["high_findings"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
