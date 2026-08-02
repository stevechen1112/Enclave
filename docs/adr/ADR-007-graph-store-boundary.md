# ADR-007 — Graph Store Boundary (Enclave PG vs WeKnora Neo4j)

**Status**: Accepted  
**Date**: 2026-08-02  
**Related**: WK-05, CV-WK-05, ADR-005

## Context

Enclave already ships `GraphService` backed by **PostgreSQL adjacency tables**
(`api_only_no_production_write`). WeKnora optionally exposes **Neo4j GraphRAG**
(`NEO4J_ENABLE` + KB `graph_enabled`). Both produce "entities" and "relations"
but they are not the same store, schema, or retrieval path.

Mixing the two under one product claim ("we have a knowledge graph") would
falsely imply a single coherent graph.

## Decision

1. **Two namespaces, never one name**
   - Enclave PG graph → product surface: `enclave.graph` / `GraphService`
   - WeKnora Neo4j → product surface: `weknora.neo4j` / GraphRAG specialist path
   - Citations and audit traces MUST record `provider=enclave|weknora` so lineage
     cannot be misread as a shared graph.

2. **Enablement gate**
   - WeKnora Neo4j stays **OFF** until CV-WK-05 ablation PROVEN on the approved
     question subset (relationship / multi-hop).
   - Even after PROVEN, Neo4j is limited to **standard / enterprise** profiles
     (not free / lite). Free tier continues to use Enclave PG graph only, if at all.

3. **No dual write**
   - A document ingested via RAGFlow DeepDOC does **not** auto-extract into
     Neo4j. Extraction into WeKnora graph requires an explicit WeKnora ingest
     with `graph_enabled=true`.
   - Enclave `GraphService` remains the only graph writable from Enclave APIs
     unless a future ADR opens a controlled projection.

4. **Retrieval fan-out**
   - Per ADR-005, Neo4j hits do not join the default fan-out until E2 admits
     the path after ablation. Until then, GraphRAG is opt-in / specialist-only.

## Consequences

- Operators must provision Neo4j separately; absence of Neo4j is not a defect
  of Enclave PG graph.
- Eval artifacts for CV-WK-05 and any PG-graph evals are kept distinct
  (`weknora_graph_ablation_last_run.json` vs future `enclave_graph_*`).
- Marketing / USER docs must say "local entity graph" vs "WeKnora Neo4j
  GraphRAG" — never "the knowledge graph" without qualifier.
