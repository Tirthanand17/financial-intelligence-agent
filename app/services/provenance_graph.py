from __future__ import annotations

from datetime import UTC, datetime

from app.services.document_detail import build_document_detail
from app.sources.registry import get_source


def _source_meta(source_id: str) -> dict[str, object]:
    try:
        source = get_source(source_id)
        return {
            "source_name": source.name,
            "authority_level": source.authority_level.value,
            "independence_group": source.independence_group or source.source_id,
            "category": source.category,
        }
    except ValueError:
        return {
            "source_name": source_id,
            "authority_level": None,
            "independence_group": source_id,
            "category": None,
        }


def build_provenance_graph(document_id: str) -> dict[str, object] | None:
    """Build a bounded read-only provenance graph from one persisted document.

    The graph is derived entirely from the existing document-detail snapshot. It
    never fetches evidence and never exposes the private raw-object reference.
    """
    detail = build_document_detail(document_id)
    if detail is None:
        return None

    document = detail["document"]
    source_id = str(document["source_id"])
    source_meta = _source_meta(source_id)

    nodes: list[dict[str, object]] = []
    edges: list[dict[str, object]] = []

    source_node = f"source:{source_id}"
    document_node = f"document:{document['document_id']}"
    nodes.append(
        {
            "id": source_node,
            "type": "source",
            "label": source_meta["source_name"],
            "metadata": {
                "source_id": source_id,
                "authority_level": source_meta["authority_level"],
                "independence_group": source_meta["independence_group"],
                "category": source_meta["category"],
            },
        }
    )
    nodes.append(
        {
            "id": document_node,
            "type": "document",
            "label": document.get("title") or document["document_id"],
            "metadata": {
                "document_id": document["document_id"],
                "sha256": document["sha256"],
                "content_type": document["content_type"],
                "retrieved_at": document["retrieved_at"],
                "chunk_count": document["chunk_count"],
                "status": document["status"],
                "raw_evidence_retained": document["raw_evidence_retained"],
                "object_reference_redacted": document["object_reference_redacted"],
            },
        }
    )
    edges.append(
        {
            "from": source_node,
            "to": document_node,
            "type": "published_evidence",
            "label": "published evidence",
        }
    )

    for index, discovery in enumerate(detail.get("discoveries", [])):
        discovery_node = f"discovery:{index}:{discovery['monitor_id']}"
        nodes.append(
            {
                "id": discovery_node,
                "type": "discovery",
                "label": str(discovery["monitor_id"]),
                "metadata": discovery,
            }
        )
        edges.append(
            {
                "from": discovery_node,
                "to": document_node,
                "type": "discovered_document",
                "label": "discovered document",
            }
        )

    claim_node_ids: dict[str, str] = {}
    for claim in detail.get("claims", []):
        claim_id = str(claim["claim_id"])
        claim_node = f"claim:{claim_id}"
        claim_node_ids[claim_id] = claim_node
        nodes.append(
            {
                "id": claim_node,
                "type": "claim",
                "label": f"{claim['entity']} — {claim['canonical_metric']}",
                "metadata": {
                    "claim_id": claim_id,
                    "entity": claim["entity"],
                    "metric": claim["metric"],
                    "canonical_metric": claim["canonical_metric"],
                    "indicator_id": claim["indicator_id"],
                    "value_text": claim["value_text"],
                    "unit": claim["unit"],
                    "publication_date": claim["publication_date"],
                    "effective_date": claim["effective_date"],
                    "state": claim["state"],
                    "quality_gate": claim["quality_gate"],
                    "confidence": claim["confidence"],
                    "evidence_chunk_index": claim["evidence_chunk_index"],
                },
            }
        )
        edges.append(
            {
                "from": document_node,
                "to": claim_node,
                "type": "extracted_claim",
                "label": f"chunk {claim['evidence_chunk_index']}",
            }
        )

        attribution = claim.get("attribution")
        if attribution is not None:
            attribution_node = f"attribution:{claim_id}"
            nodes.append(
                {
                    "id": attribution_node,
                    "type": "entity_attribution",
                    "label": str(attribution["canonical_entity"]),
                    "metadata": attribution,
                }
            )
            edges.append(
                {
                    "from": claim_node,
                    "to": attribution_node,
                    "type": "attributed_as",
                    "label": str(attribution["basis"]),
                }
            )

        for event_index, event in enumerate(claim.get("verification_events", [])):
            event_node = f"verification:{claim_id}:{event_index}"
            nodes.append(
                {
                    "id": event_node,
                    "type": "verification_event",
                    "label": f"{event['from_state']} → {event['to_state']}",
                    "metadata": event,
                }
            )
            edges.append(
                {
                    "from": claim_node,
                    "to": event_node,
                    "type": "verification_event",
                    "label": str(event["reason"]),
                }
            )

        for event_index, event in enumerate(claim.get("trust_events", [])):
            event_node = f"trust:{claim_id}:{event_index}"
            nodes.append(
                {
                    "id": event_node,
                    "type": "trust_event",
                    "label": f"{event['from_state']} → {event['to_state']}",
                    "metadata": event,
                }
            )
            edges.append(
                {
                    "from": claim_node,
                    "to": event_node,
                    "type": "trust_event",
                    "label": str(event["reason"]),
                }
            )

    for claim in detail.get("claims", []):
        claim_id = str(claim["claim_id"])
        current_node = claim_node_ids[claim_id]
        superseded_by = claim.get("superseded_by")
        if superseded_by is not None:
            newer_id = str(superseded_by["claim_id"])
            newer_node = claim_node_ids.get(newer_id, f"claim:{newer_id}")
            if newer_id not in claim_node_ids:
                nodes.append(
                    {
                        "id": newer_node,
                        "type": "external_claim_reference",
                        "label": newer_id,
                        "metadata": {"claim_id": newer_id, "not_in_document_scope": True},
                    }
                )
            edges.append(
                {
                    "from": current_node,
                    "to": newer_node,
                    "type": "superseded_by",
                    "label": f"{superseded_by['older_date']} → {superseded_by['newer_date']}",
                }
            )

    node_type_counts: dict[str, int] = {}
    for node in nodes:
        node_type = str(node["type"])
        node_type_counts[node_type] = node_type_counts.get(node_type, 0) + 1

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "read_only_provenance_graph",
        "document_id": document["document_id"],
        "summary": {
            "nodes": len(nodes),
            "edges": len(edges),
            "node_type_counts": dict(sorted(node_type_counts.items())),
        },
        "nodes": nodes,
        "edges": edges,
        "safety": {
            "read_only": True,
            "mutates_data": False,
            "network_crawling": False,
            "downloads_raw_evidence": False,
            "exposes_object_keys": False,
            "enables_trust_promotion": False,
            "note": (
                "The graph is a visualization of persisted provenance and audit relationships. "
                "It does not create, repair, rewrite, verify, trust, delete, or fetch evidence."
            ),
        },
    }
