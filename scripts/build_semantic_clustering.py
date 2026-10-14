import argparse
import json
import shutil
from collections import Counter
from pathlib import Path

from audit_semantic_clustering import audit_semantic_clustering, load_json, save_json


CLUSTER_FILES = [
    "semantic_clusters.json",
    "cluster_memberships.json",
    "cluster_bridges.json",
    "cluster_routing.json",
    "cluster_artifact_contracts.json",
]


def normalize_bridge_status(bridge):
    value = bridge.get("approved_for_composition", "")
    if value == "APPROVED":
        return "APPROVED"
    if value == "BLOCKED":
        return "BLOCKED"
    if value == "VALIDATED":
        return "VALIDATED"
    return "DISCOVERED"


def load_upstream_for_scope_review(offline_root):
    root = Path(offline_root)
    classes = load_json(root / "02_object_ontology" / "ontology_classes.json")["classes"]
    derived_classes = load_json(root / "02_object_ontology" / "ontology_derived_classes.json")["derived_classes"]
    method_contracts = load_json(root / "04_method_contracts" / "method_contracts.json")["method_contracts"]
    business_methods = load_json(root / "02_object_ontology" / "ontology_method_candidates.json")["method_candidates"]
    return classes, derived_classes, business_methods, method_contracts


def class_table_footprint(classes, derived_classes):
    footprint = {}
    for item in classes:
        footprint[item["class_id"]] = set(item.get("source_tables", [item.get("source_table")]))
    for item in derived_classes:
        footprint[item["class_id"]] = set(item.get("source_tables", []))
    return footprint


def build_method_contract_owner_scope_review(offline_root):
    classes, derived_classes, business_methods, method_contracts = load_upstream_for_scope_review(offline_root)
    footprints = class_table_footprint(classes, derived_classes)
    method_by_id = {item["method_id"]: item for item in business_methods}
    cases = []

    for contract in method_contracts:
        method_id = contract["method_id"]
        method = method_by_id.get(method_id, {})
        owner_class = method.get("method_owner_class") or contract.get("method_owner_class")
        owner_tables = footprints.get(owner_class, set())
        required_tables = set(contract.get("required_tables", []))
        outside_owner = sorted(required_tables - owner_tables)
        if not outside_owner:
            continue
        cases.append(
            {
                "method_id": method_id,
                "owner": owner_class,
                "owner_table_footprint": sorted(owner_tables),
                "contract_tables_outside_owner": outside_owner,
                "interpretation": "Method contract required_tables is method-level union across scenarios; inspect per-scenario/per-variant contract before declaring execution invalid.",
            }
        )

    return {
        "requires_review_count": len(cases),
        "total_methods": len(method_contracts),
        "cases": cases,
    }


def normalize_artifact_metadata(data, database_id, artifact_name):
    normalized = dict(data)
    normalized["artifact"] = artifact_name
    normalized["database_id"] = database_id
    normalized["version"] = "v01"
    normalized["construction_source"] = "proposal_seed+upstream_artifact_validation"
    return normalized


def normalize_semantic_clusters(data, database_id):
    return normalize_artifact_metadata(data, database_id, "semantic_clusters")


def normalize_cluster_memberships(data, database_id):
    return normalize_artifact_metadata(data, database_id, "cluster_memberships")


def normalize_cluster_routing(data, database_id):
    return normalize_artifact_metadata(data, database_id, "cluster_routing")


def normalize_cluster_bridges(data, database_id):
    normalized = normalize_artifact_metadata(data, database_id, "cluster_bridges")
    bridges = []
    for bridge in normalized.get("bridges", []):
        item = dict(bridge)
        item["composition_status"] = item.get("composition_status") or normalize_bridge_status(item)
        item["composition_status_note"] = (
            "DISCOVERED means the relation exists but is not approved for query composition yet."
            if item["composition_status"] == "DISCOVERED"
            else ""
        )
        bridges.append(item)
    normalized["bridges"] = bridges
    return normalized


def build_coverage_audit_from_audit(database_id, audit, offline_root, cluster_bridges):
    coverage = audit["coverage_summary"]
    _, derived_classes, _, _ = load_upstream_for_scope_review(offline_root)
    return {
        "artifact": "cluster_coverage_audit",
        "version": "v01",
        "database_id": database_id,
        "coverage": coverage,
        "derived_class_source_counts": {
            item["class_id"]: len(item.get("source_classes", []))
            for item in derived_classes
        },
        "method_contract_owner_scope_review": build_method_contract_owner_scope_review(offline_root),
        "nullable_fk_relations_with_inner_join_to_review": [
            item["relation_id"]
            for item in cluster_bridges.get("bridges", [])
            if item.get("source_fk_nullable") and item.get("physical_join", {}).get("join_type") == "INNER"
        ],
        "known_limitations": [
            "Coverage readiness does not prove semantic correctness.",
            "Bridge composition defaults to DISCOVERED unless explicitly approved.",
            "Method contract required_tables can still be a scenario union until Method Contract Normalization v02.",
        ],
        "coverage_readiness_status": "PASS" if audit["high_findings"] == 0 else "FAIL",
        "semantic_readiness_status": "NOT_ASSESSED_HERE",
        "audit_summary": {
            "finding_count": audit["finding_count"],
            "high_findings": audit["high_findings"],
            "medium_findings": audit["medium_findings"],
            "finding_count_by_category": audit["finding_count_by_category"],
        },
        "note": "Coverage audit only checks assignment/routing consistency. Semantic contract readiness is handled separately.",
    }


def copy_contracts_if_present(proposal_dir, output_dir):
    source = Path(proposal_dir) / "cluster_artifact_contracts.json"
    if source.exists():
        shutil.copy2(source, Path(output_dir) / "cluster_artifact_contracts.json")


def build_manifest(database_id, offline_root, proposal_dir, output_dir, audit):
    output_dir = Path(output_dir)
    readiness_status = "READY" if audit["high_findings"] == 0 else "NOT_READY"
    return {
        "database_id": database_id,
        "artifact_type": "semantic_clustering",
        "version": "v01",
        "construction_mode": "proposal_seed_validated_against_upstream",
        "input_offline_root": str(offline_root),
        "input_proposal_dir": str(proposal_dir),
        "readiness_status": readiness_status,
        "output_files": {
            "semantic_clusters": str(output_dir / "semantic_clusters.json"),
            "cluster_memberships": str(output_dir / "cluster_memberships.json"),
            "cluster_bridges": str(output_dir / "cluster_bridges.json"),
            "cluster_routing": str(output_dir / "cluster_routing.json"),
            "cluster_coverage_audit": str(output_dir / "cluster_coverage_audit.json"),
            "semantic_clustering_audit": str(output_dir / "semantic_clustering_audit.json"),
            "semantic_clustering_manifest": str(output_dir / "semantic_clustering_manifest.json"),
        },
        "counts": {
            "clusters": audit["coverage_summary"].get("cluster_count", 0),
            "base_classes_assigned": audit["coverage_summary"]["base_classes"]["assigned"],
            "derived_classes_assigned": audit["coverage_summary"]["derived_classes"]["assigned"],
            "properties_assigned": audit["coverage_summary"]["properties"]["assigned"],
            "relations_mapped": audit["coverage_summary"]["relations"]["mapped"],
            "business_methods_assigned": audit["coverage_summary"]["business_methods"]["assigned"],
            "scenarios_routed": audit["coverage_summary"]["scenarios"]["routed"],
            "audit_findings": audit["finding_count"],
            "high_findings": audit["high_findings"],
            "medium_findings": audit["medium_findings"],
        },
    }


def build_semantic_clustering(database_id, offline_root, proposal_dir, output_dir):
    proposal_dir = Path(proposal_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    semantic_clusters = normalize_semantic_clusters(load_json(proposal_dir / "semantic_clusters.json"), database_id)
    cluster_memberships = normalize_cluster_memberships(load_json(proposal_dir / "cluster_memberships.json"), database_id)
    cluster_bridges = normalize_cluster_bridges(load_json(proposal_dir / "cluster_bridges.json"), database_id)
    cluster_routing = normalize_cluster_routing(load_json(proposal_dir / "cluster_routing.json"), database_id)

    save_json(semantic_clusters, output_dir / "semantic_clusters.json")
    save_json(cluster_memberships, output_dir / "cluster_memberships.json")
    save_json(cluster_bridges, output_dir / "cluster_bridges.json")
    save_json(cluster_routing, output_dir / "cluster_routing.json")
    copy_contracts_if_present(proposal_dir, output_dir)

    initial_audit = audit_semantic_clustering(
        database_id=database_id,
        offline_root=offline_root,
        clustering_dir=output_dir,
    )
    initial_audit["coverage_summary"]["cluster_count"] = len(semantic_clusters.get("clusters", []))

    coverage_audit = build_coverage_audit_from_audit(database_id, initial_audit, offline_root, cluster_bridges)
    save_json(coverage_audit, output_dir / "cluster_coverage_audit.json")

    final_audit = audit_semantic_clustering(
        database_id=database_id,
        offline_root=offline_root,
        clustering_dir=output_dir,
    )
    final_audit["coverage_summary"]["cluster_count"] = len(semantic_clusters.get("clusters", []))
    coverage_audit = build_coverage_audit_from_audit(database_id, final_audit, offline_root, cluster_bridges)
    manifest = build_manifest(database_id, offline_root, proposal_dir, output_dir, final_audit)

    save_json(coverage_audit, output_dir / "cluster_coverage_audit.json")
    save_json(final_audit, output_dir / "semantic_clustering_audit.json")
    save_json(manifest, output_dir / "semantic_clustering_manifest.json")
    return manifest


def build_parser():
    parser = argparse.ArgumentParser(description="Build semantic clustering artifacts from proposal seed and upstream offline artifacts.")
    parser.add_argument("--database-id", required=True)
    parser.add_argument("--offline-root", required=True)
    parser.add_argument("--proposal-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    manifest = build_semantic_clustering(
        database_id=args.database_id,
        offline_root=Path(args.offline_root),
        proposal_dir=Path(args.proposal_dir),
        output_dir=Path(args.output_dir),
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))

    if manifest["readiness_status"] != "READY":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
