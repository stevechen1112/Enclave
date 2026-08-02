"""
Phase 1 — Gateway Result Aggregator

Deduplicate, normalize scores, and fuse multi-adapter retrieval results.
"""
from __future__ import annotations

import hashlib
from typing import Dict, List, Set

from app.gateway.contracts import ChunkResult


class ResultAggregator:
    """Merge results from multiple adapters."""

    def normalize_scores(self, results: List[ChunkResult]) -> List[ChunkResult]:
        if not results:
            return results
        scores = [r.score for r in results]
        min_s, max_s = min(scores), max(scores)
        if max_s == min_s:
            return sorted(results, key=lambda r: r.score, reverse=True)
        for r in results:
            r.score = (r.score - min_s) / (max_s - min_s)
        return sorted(results, key=lambda r: r.score, reverse=True)

    def deduplicate(self, results: List[ChunkResult]) -> List[ChunkResult]:
        seen: Set[str] = set()
        unique: List[ChunkResult] = []
        for r in results:
            content_hash = hashlib.sha256((r.content or "")[:500].encode()).hexdigest()[:16]
            doc_id = r.document_id or "unknown"
            key = f"{doc_id}:{content_hash}"
            if key in seen:
                continue
            seen.add(key)
            unique.append(r)
        return unique

    def fuse_rrf(
        self,
        result_lists: List[List[ChunkResult]],
        top_k: int = 20,
        rrf_k: int = 60,
    ) -> List[ChunkResult]:
        if not result_lists:
            return []
        if len(result_lists) == 1:
            return result_lists[0][:top_k]

        rrf_scores: Dict[str, float] = {}
        result_map: Dict[str, ChunkResult] = {}

        for results in result_lists:
            for rank, r in enumerate(results):
                key = r.id or f"{r.document_id}:{rank}"
                rrf_scores[key] = rrf_scores.get(key, 0) + 1.0 / (rrf_k + rank + 1)
                if key not in result_map:
                    result_map[key] = r

        sorted_keys = sorted(rrf_scores, key=lambda k: rrf_scores[k], reverse=True)
        fused: List[ChunkResult] = []
        for key in sorted_keys[:top_k]:
            item = result_map[key]
            item.score = round(rrf_scores[key], 6)
            fused.append(item)
        return fused

    def aggregate(
        self,
        results: List[ChunkResult],
        top_k: int = 20,
    ) -> List[ChunkResult]:
        normalized = self.normalize_scores(results)
        deduped = self.deduplicate(normalized)
        return deduped[:top_k]
