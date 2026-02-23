"""
UniHR 進階知識庫檢索服務 (Advanced Knowledge Base Retriever)

功能：
  - 語意檢索（pgvector + Voyage Embedding）
  - 關鍵字檢索（BM25）
  - 混合檢索（語意 + BM25 + RRF 融合）
  - 相似度閾值過濾
  - 重排序（Voyage Rerank）
  - Redis 查詢快取
  - 批次搜尋
"""

import hashlib
import json
import logging
import re
from typing import List, Dict, Any, Optional
from uuid import UUID

import voyageai

from app.config import settings
from app.db.session import SessionLocal
from app.models.document import DocumentChunk, Document

logger = logging.getLogger(__name__)

# ── 可選依賴 ──
try:
    import redis as redis_lib
    _HAS_REDIS = True
except ImportError:
    _HAS_REDIS = False

try:
    from rank_bm25 import BM25Okapi
    _HAS_BM25 = True
except ImportError:
    _HAS_BM25 = False

try:
    import jieba
    _HAS_JIEBA = True
except ImportError:
    _HAS_JIEBA = False

try:
    import openai as openai_lib
    _HAS_OPENAI = True
except ImportError:
    _HAS_OPENAI = False


class KnowledgeBaseRetriever:
    """
    進階知識庫檢索服務。

    支援三種檢索模式：
      1. ``semantic``  – 純語意向量檢索（預設）
      2. ``keyword``   – 純 BM25 關鍵字檢索
      3. ``hybrid``    – 語意 + BM25 + RRF 融合 + 重排序
    """

    def __init__(self):
        if not settings.VOYAGE_API_KEY:
            raise ValueError("VOYAGE_API_KEY 未設定")

        self.voyage_client = voyageai.Client(api_key=settings.VOYAGE_API_KEY)

        # OpenAI client（用於 HyDE 查詢擴展）
        self._openai = None
        openai_key = getattr(settings, "OPENAI_API_KEY", "")
        if _HAS_OPENAI and openai_key:
            self._openai = openai_lib.OpenAI(api_key=openai_key)

        # Redis 快取
        self._redis = None
        if _HAS_REDIS and getattr(settings, "REDIS_HOST", None):
            try:
                self._redis = redis_lib.Redis(
                    host=settings.REDIS_HOST,
                    port=settings.REDIS_PORT,
                    db=1,  # 用 db=1 做檢索快取（db=0 給 Celery）
                    decode_responses=True,
                    socket_connect_timeout=2,
                )
                self._redis.ping()
            except Exception:
                logger.warning("Redis 連線失敗，檢索快取已停用")
                self._redis = None

    # ─────────────────────────────────────────────
    # 公開 API
    # ─────────────────────────────────────────────

    def search(
        self,
        tenant_id: UUID,
        query: str,
        top_k: int = 5,
        mode: str = "hybrid",
        min_score: float = 0.0,
        rerank: bool = True,
        use_cache: bool = True,
        filter_dict: Optional[Dict] = None,
    ) -> List[Dict[str, Any]]:
        """
        在租戶知識庫中搜尋相關內容。

        Args:
            tenant_id: 租戶 ID
            query: 查詢問題
            top_k: 返回結果數量
            mode: 檢索模式 (semantic / keyword / hybrid)
            min_score: 相似度閾值（0.0 ~ 1.0）
            rerank: 是否使用重排序
            use_cache: 是否使用 Redis 快取
            filter_dict: 額外的 metadata 過濾條件

        Returns:
            匹配結果列表，每個包含 content / score / metadata 等。
        """
        # 1. 快取檢查
        if use_cache and self._redis:
            cached = self._cache_get(tenant_id, query, mode, top_k, min_score)
            if cached is not None:
                return cached

        # 1.5 Query Expansion（HyDE 假設文件生成）
        expanded_query = None
        if mode in {"semantic", "hybrid"}:
            expanded_query = self._expand_query(query)

        # 2. 執行檢索（語意使用擴展查詢，BM25 保持原始 query）
        if mode == "keyword":
            results = self._keyword_search(tenant_id, query, top_k=top_k * 2)
        elif mode == "hybrid":
            semantic_query = expanded_query or query
            results = self._hybrid_search(
                tenant_id,
                semantic_query=semantic_query,
                keyword_query=query,
                top_k=top_k * 2,
                filter_dict=filter_dict,
            )
        else:  # semantic
            search_query = expanded_query or query
            results = self._semantic_search(
                tenant_id, search_query, top_k=top_k * 2, filter_dict=filter_dict,
            )

        # 3. 閾值過濾
        if min_score > 0:
            results = [r for r in results if r.get("score", 0) >= min_score]

        # 4. 重排序
        if rerank and len(results) > 1:
            results = self._rerank(query, results, top_k=top_k)
        else:
            results = results[:top_k]

        # 5. 寫入快取
        if use_cache and self._redis:
            self._cache_set(tenant_id, query, mode, top_k, min_score, results)

        return results

    def batch_search(
        self,
        tenant_id: UUID,
        queries: List[str],
        top_k: int = 5,
        mode: str = "hybrid",
    ) -> List[List[Dict[str, Any]]]:
        """批次搜尋"""
        return [self.search(tenant_id, q, top_k=top_k, mode=mode) for q in queries]

    def get_stats(self, tenant_id: UUID) -> Dict[str, Any]:
        """獲取租戶知識庫統計資訊（從 PostgreSQL 查詢）"""
        db = SessionLocal()
        try:
            vector_count = (
                db.query(DocumentChunk)
                .filter(
                    DocumentChunk.tenant_id == tenant_id,
                    DocumentChunk.embedding.isnot(None),
                )
                .count()
            )
            total_chunks = (
                db.query(DocumentChunk)
                .filter(DocumentChunk.tenant_id == tenant_id)
                .count()
            )
            return {
                "exists": total_chunks > 0,
                "vector_count": vector_count,
                "total_chunks": total_chunks,
                "dimension": settings.EMBEDDING_DIMENSION,
                "backend": "pgvector",
            }
        except Exception as e:
            return {"exists": False, "error": str(e)}
        finally:
            db.close()

    # ─────────────────────────────────────────────
    # 語意檢索
    # ─────────────────────────────────────────────

    def _semantic_search(
        self,
        tenant_id: UUID,
        query: str,
        top_k: int = 10,
        filter_dict: Optional[Dict] = None,
    ) -> List[Dict[str, Any]]:
        """使用 pgvector 的 cosine distance 進行語意檢索"""
        db = SessionLocal()
        try:
            # 1. 取得查詢向量
            query_embedding = self.voyage_client.embed(
                [query], model=settings.VOYAGE_MODEL, input_type="query",
            ).embeddings[0]

            # 2. 使用 pgvector cosine distance 搜尋
            #    cosine_distance = 1 - cosine_similarity
            #    所以 score = 1 - cosine_distance
            query_obj = (
                db.query(
                    DocumentChunk,
                    DocumentChunk.embedding.cosine_distance(query_embedding).label("distance"),
                )
                .filter(
                    DocumentChunk.tenant_id == tenant_id,
                    DocumentChunk.embedding.isnot(None),
                )
            )

            # ── filter_dict：metadata 過濾 ──
            if filter_dict:
                for key, value in filter_dict.items():
                    if isinstance(value, list):
                        # IN 條件：metadata_json->>'key' IN (...)
                        query_obj = query_obj.filter(
                            DocumentChunk.metadata_json[key].astext.in_(
                                [str(v) for v in value]
                            )
                        )
                    else:
                        # 精確比對：metadata_json->>'key' = value
                        query_obj = query_obj.filter(
                            DocumentChunk.metadata_json[key].astext == str(value)
                        )

            query_obj = (
                query_obj
                .order_by(DocumentChunk.embedding.cosine_distance(query_embedding))
                .limit(top_k)
            )

            results = []
            # 取得文件名映射
            doc_map: Dict[UUID, str] = {}
            for chunk, distance in query_obj.all():
                # 懶查文件名
                if chunk.document_id not in doc_map:
                    doc = db.query(Document).filter(Document.id == chunk.document_id).first()
                    doc_map[chunk.document_id] = doc.filename if doc else ""

                score = round(1.0 - distance, 4)  # cosine similarity
                results.append({
                    "id": str(chunk.id),
                    "score": score,
                    "content": chunk.text or "",
                    "document_id": str(chunk.document_id),
                    "filename": doc_map.get(chunk.document_id, ""),
                    "chunk_index": chunk.chunk_index,
                    "metadata": chunk.metadata_json or {},
                    "source": "semantic",
                })

            return results
        except Exception as e:
            logger.error(f"語意檢索錯誤: {e}")
            return []
        finally:
            db.close()

    # ─────────────────────────────────────────────
    # BM25 關鍵字檢索
    # ─────────────────────────────────────────────

    def _keyword_search(
        self,
        tenant_id: UUID,
        query: str,
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        """使用 BM25 在 DB chunks 上做關鍵字檢索"""
        if not _HAS_BM25:
            logger.warning("rank_bm25 未安裝，關鍵字檢索不可用")
            return []

        try:
            db = SessionLocal()
            try:
                chunks = (
                    db.query(DocumentChunk)
                    .filter(DocumentChunk.tenant_id == tenant_id)
                    .all()
                )
                if not chunks:
                    return []

                # 取得文件名映射
                doc_ids = list({c.document_id for c in chunks})
                docs = db.query(Document).filter(Document.id.in_(doc_ids)).all()
                doc_map = {d.id: d.filename for d in docs}
            finally:
                db.close()

            # 建立 BM25 索引
            corpus = [self._tokenize(c.text or "") for c in chunks]
            bm25 = BM25Okapi(corpus)

            query_tokens = self._tokenize(query)
            scores = bm25.get_scores(query_tokens)

            # 取 Top-K
            ranked = sorted(
                enumerate(scores), key=lambda x: x[1], reverse=True
            )[:top_k]

            results = []
            max_score = max(scores) if max(scores) > 0 else 1.0
            for idx, score in ranked:
                if score <= 0:
                    continue
                chunk = chunks[idx]
                results.append({
                    "id": str(chunk.id),
                    "score": round(score / max_score, 4),  # 正規化到 0~1
                    "content": chunk.text or "",
                    "document_id": str(chunk.document_id),
                    "filename": doc_map.get(chunk.document_id, ""),
                    "chunk_index": chunk.chunk_index,
                    "metadata": {},
                    "source": "keyword",
                })
            return results
        except Exception as e:
            logger.error(f"BM25 關鍵字檢索錯誤: {e}")
            return []

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """中英文混合分詞（jieba 詞級分詞 + 英文空格分詞）"""
        if _HAS_JIEBA:
            # jieba 精確模式：「勞動基準法」→「勞動」「基準」「法」
            # 比逐字分詞精確度高很多
            tokens = list(jieba.cut(text, cut_all=False))
            return [t.strip().lower() for t in tokens if t.strip() and len(t.strip()) > 0]

        # Fallback：逐字 + 英文按詞
        tokens: List[str] = []
        current_word = ""
        for char in text:
            if "\u4e00" <= char <= "\u9fff":
                if current_word:
                    tokens.append(current_word.lower())
                    current_word = ""
                tokens.append(char)
            elif char.isalnum():
                current_word += char
            else:
                if current_word:
                    tokens.append(current_word.lower())
                    current_word = ""
        if current_word:
            tokens.append(current_word.lower())
        return [t for t in tokens if len(t.strip()) > 0]

    # ─────────────────────────────────────────────
    # 混合檢索（RRF 融合）
    # ─────────────────────────────────────────────

    def _hybrid_search(
        self,
        tenant_id: UUID,
        semantic_query: str,
        keyword_query: str,
        top_k: int = 10,
        filter_dict: Optional[Dict] = None,
        rrf_k: int = 60,
    ) -> List[Dict[str, Any]]:
        """
        混合檢索：語意 + BM25，使用 Reciprocal Rank Fusion (RRF) 合併。

        RRF 公式: score = Σ 1 / (k + rank)
        """
        semantic_results = self._semantic_search(
            tenant_id, semantic_query, top_k=top_k, filter_dict=filter_dict
        )
        keyword_results = self._keyword_search(tenant_id, keyword_query, top_k=top_k)

        # 如果只有一種來源有結果，直接返回
        if not keyword_results:
            return semantic_results
        if not semantic_results:
            return keyword_results

        # RRF 融合
        rrf_scores: Dict[str, float] = {}
        result_map: Dict[str, Dict[str, Any]] = {}

        for rank, r in enumerate(semantic_results):
            key = r.get("id", f"sem-{rank}")
            rrf_scores[key] = rrf_scores.get(key, 0) + 1.0 / (rrf_k + rank + 1)
            result_map[key] = r

        for rank, r in enumerate(keyword_results):
            key = r.get("id", f"kw-{rank}")
            rrf_scores[key] = rrf_scores.get(key, 0) + 1.0 / (rrf_k + rank + 1)
            if key not in result_map:
                result_map[key] = r

        # 按 RRF 分數排序
        sorted_keys = sorted(rrf_scores, key=lambda k: rrf_scores[k], reverse=True)

        merged: List[Dict[str, Any]] = []
        for key in sorted_keys[:top_k]:
            item = result_map[key].copy()
            item["score"] = round(rrf_scores[key], 6)
            item["source"] = "hybrid"
            merged.append(item)

        return merged

    # ─────────────────────────────────────────────
    # 重排序（Voyage Rerank）
    # ─────────────────────────────────────────────

    def _rerank(
        self,
        query: str,
        results: List[Dict[str, Any]],
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        使用 Voyage AI Rerank API 重新排序結果。
        若 API 不可用則回退到原始排序。
        """
        if not results:
            return results

        try:
            documents = [r.get("content", "")[:2000] for r in results]

            reranked = self.voyage_client.rerank(
                query=query,
                documents=documents,
                model="rerank-2",
                top_k=min(top_k, len(documents)),
            )

            reranked_results: List[Dict[str, Any]] = []
            for item in reranked.results:
                original = results[item.index].copy()
                original["score"] = round(item.relevance_score, 4)
                original["reranked"] = True
                reranked_results.append(original)

            return reranked_results

        except Exception as e:
            logger.warning(f"重排序失敗，回退到原始排序: {e}")
            return results[:top_k]

    # ─────────────────────────────────────────────
    # Redis 快取
    # ─────────────────────────────────────────────

    _CACHE_TTL = 300  # 5 分鐘

    def _cache_key(
        self, tenant_id: UUID, query: str, mode: str, top_k: int, min_score: float
    ) -> str:
        raw = f"{tenant_id}:{query}:{mode}:{top_k}:{min_score}"
        h = hashlib.sha256(raw.encode()).hexdigest()[:16]
        return f"kb:search:{h}"

    def _cache_get(
        self, tenant_id: UUID, query: str, mode: str, top_k: int, min_score: float
    ) -> Optional[List[Dict[str, Any]]]:
        if not self._redis:
            return None
        try:
            key = self._cache_key(tenant_id, query, mode, top_k, min_score)
            cached = self._redis.get(key)
            if cached:
                logger.debug(f"快取命中: {key}")
                return json.loads(cached)
        except Exception:
            pass
        return None

    def _cache_set(
        self,
        tenant_id: UUID,
        query: str,
        mode: str,
        top_k: int,
        min_score: float,
        results: List[Dict[str, Any]],
    ):
        if not self._redis:
            return
        try:
            key = self._cache_key(tenant_id, query, mode, top_k, min_score)
            self._redis.setex(key, self._CACHE_TTL, json.dumps(results, default=str))
        except Exception:
            pass

    def invalidate_cache(self, tenant_id: UUID):
        """清除租戶的所有檢索快取（文件新增/刪除時呼叫）"""
        if not self._redis:
            return
        try:
            # 刪除所有此租戶的快取 key
            cursor = 0
            while True:
                cursor, keys = self._redis.scan(cursor, match="kb:search:*", count=100)
                if keys:
                    self._redis.delete(*keys)
                if cursor == 0:
                    break
        except Exception:
            pass

    # ─────────────────────────────────────────────
    # HyDE 查詢擴展（Hypothetical Document Embeddings）
    # ─────────────────────────────────────────────

    def _expand_query(self, query: str) -> Optional[str]:
        """
        HyDE 查詢擴展（已停用）。

        效能分析：此方法為同步阻塞 OpenAI 呼叫（~1.1s），且 search() 是
        同步函式，在 asyncio.gather() 中無法真正並行，導致每次問答
        額外增加 2.2s 延遲。在 voyage-4-lite + rerank 已有效的情況下，
        HyDE 的精度增益不足以抵消延遲代價，故停用。
        """
        return None
