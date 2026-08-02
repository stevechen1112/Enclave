"""
Enclave 進階知識庫檢索服務（Advanced Knowledge Base Retriever）

功能：
  - 語意檢索（pgvector + Ollama/Voyage Embedding）
  - 關鍵字檢索（BM25）
  - 混合檢索（語意 + BM25 + RRF 融合）
  - 相似度閾值過濾
  - 重排序（Voyage Rerank）
  - Redis 查詢快取（ACL-aware：cache key 包含 policy fingerprint）
  - 批次搜尋

Phase 0 安全修復：
  - search() 接受 AuthorizationContext，不再只接受 tenant_id
  - 所有檢索模式（semantic/keyword/hybrid）使用相同 ACL predicate
  - 快取鍵包含 policy_fingerprint，防止跨使用者快取洩漏
  - 權限變更時精確失效相關 cache
"""

import hashlib
import json
import logging
import re
from typing import List, Dict, Any, Optional
from uuid import UUID

from app.config import settings
from app.services.deployment_mode import resolve_runtime_profiles_no_db
from app.db.session import SessionLocal
from app.models.document import DocumentChunk, Document
from app.core.authorization import AuthorizationContext, SearchScope
from sqlalchemy import or_, and_, exists
from app.models.connector import SourceAclEntry, ExternalPrincipal

logger = logging.getLogger(__name__)

# ── 可選依賴 ──
try:
    import voyageai as _voyageai_lib
    _HAS_VOYAGE = True
except ImportError:
    _HAS_VOYAGE = False

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
        runtime = resolve_runtime_profiles_no_db()
        embed_cfg = runtime.get("embedding", {})
        self._embedding_provider = str(embed_cfg.get("provider", getattr(settings, "EMBEDDING_PROVIDER", "voyage"))).lower()
        self._embedding_model = str(embed_cfg.get("model", getattr(settings, "OLLAMA_EMBED_MODEL", "bge-m3")))

        if self._embedding_provider == "ollama":
            self.voyage_client = None  # not needed
        else:
            if not settings.VOYAGE_API_KEY:
                raise ValueError("VOYAGE_API_KEY 未設定（或改用 EMBEDDING_PROVIDER=ollama）")
            self.voyage_client = _voyageai_lib.Client(api_key=settings.VOYAGE_API_KEY)

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

    def _apply_source_acl_filter(self, query_obj, tenant_id: UUID, authz: AuthorizationContext, db):
        """
        Filter connector-sourced documents by source ACL projection.

        Fail-closed：無 mapped principal 時，connector 來源文件全部不可見。
        """
        if authz.has_kb_admin:
            return query_obj

        principal_rows = (
            db.query(ExternalPrincipal.id)
            .filter(
                ExternalPrincipal.tenant_id == tenant_id,
                ExternalPrincipal.mapped_subject_id == authz.subject_id,
            )
            .all()
        )
        principal_ids = [row[0] for row in principal_rows]

        if not principal_ids:
            # 無映射 → 僅允許非 connector 來源
            return query_obj.filter(Document.source_system.is_(None))

        allow_exists = (
            db.query(SourceAclEntry.id)
            .filter(
                SourceAclEntry.tenant_id == tenant_id,
                SourceAclEntry.source_record_id == Document.source_record_id,
                SourceAclEntry.principal_id.in_(principal_ids),
                SourceAclEntry.effect == "allow",
            )
            .correlate(Document)
            .exists()
        )
        deny_exists = (
            db.query(SourceAclEntry.id)
            .filter(
                SourceAclEntry.tenant_id == tenant_id,
                SourceAclEntry.source_record_id == Document.source_record_id,
                SourceAclEntry.principal_id.in_(principal_ids),
                SourceAclEntry.effect == "deny",
            )
            .correlate(Document)
            .exists()
        )
        return query_obj.filter(
            or_(
                Document.source_system.is_(None),
                and_(Document.source_record_id.isnot(None), allow_exists, ~deny_exists),
            )
        )

    def _apply_department_acl_filter(self, query_obj, authz: AuthorizationContext):
        """與 DocumentList / Agent 同一 PEP（含祖先；僅 kb_admin bypass）。"""
        dept_ids = authz.department_filter_ids()
        if dept_ids is None:
            return query_obj
        if dept_ids:
            return query_obj.filter(
                (Document.department_id.is_(None)) |
                (Document.department_id.in_(dept_ids))
            )
        return query_obj.filter(Document.department_id.is_(None))

    # ─────────────────────────────────────────────
    # 公開 API（Phase 0：接受 AuthorizationContext）
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
        authz: Optional[AuthorizationContext] = None,
    ) -> List[Dict[str, Any]]:
        """
        在租戶知識庫中搜尋相關內容。

        Args:
            tenant_id: 租戶 ID（向後相容；若提供 authz 則以 authz.tenant_id 為準）
            authz: 授權上下文（Phase 0 新增）。若提供，則：
                   - 檢索時套用部門 ACL 過濾
                   - 快取鍵包含 policy_fingerprint
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
        # 使用 authz 的 tenant_id（若提供）
        effective_tenant_id = authz.tenant_id if authz else tenant_id

        # 1. 快取檢查（ACL-aware：包含 policy_fingerprint）
        if use_cache and self._redis:
            cached = self._cache_get(effective_tenant_id, query, mode, top_k, min_score, authz)
            if cached is not None:
                return cached

        # 1.5 Query Expansion（HyDE 假設文件生成）
        expanded_query = None
        if mode in {"semantic", "hybrid"}:
            expanded_query = self._expand_query(query)

        # 2. 執行檢索（傳遞 authz 做 ACL 過濾）
        if mode == "keyword":
            results = self._keyword_search(effective_tenant_id, query, top_k=top_k * 2, authz=authz)
        elif mode == "hybrid":
            semantic_query = expanded_query or query
            results = self._hybrid_search(
                effective_tenant_id,
                semantic_query=semantic_query,
                keyword_query=query,
                top_k=top_k * 2,
                filter_dict=filter_dict,
                authz=authz,
            )
        else:  # semantic
            search_query = expanded_query or query
            results = self._semantic_search(
                effective_tenant_id, search_query, top_k=top_k * 2, filter_dict=filter_dict, authz=authz,
            )

        # 3. 閾值過濾
        if min_score > 0:
            results = [r for r in results if r.get("score", 0) >= min_score]

        # 4. 重排序
        if rerank and len(results) > 1:
            results = self._rerank(query, results, top_k=top_k)
        else:
            results = results[:top_k]

        # 5. Deny-set 後過濾（與 Gateway 對齊；fail-closed on lookup errors）
        if authz is not None and results:
            results = self._filter_denied(results, authz)

        # 6. 寫入快取（ACL-aware）
        if use_cache and self._redis:
            self._cache_set(effective_tenant_id, query, mode, top_k, min_score, results, authz)

        return results

    def _filter_denied(self, results: List[Dict[str, Any]], authz: AuthorizationContext) -> List[Dict[str, Any]]:
        try:
            from app.gateway.authorization import get_gateway_authorizer
            authorizer = get_gateway_authorizer()
            kept = []
            for r in results:
                doc_id = r.get("document_id")
                if doc_id and authorizer.is_denied(str(doc_id), authz.subject_id):
                    continue
                kept.append(r)
            return kept
        except Exception as exc:
            logger.warning("deny-set filter failed, fail closed empty: %s", exc)
            return []

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
        authz: Optional[AuthorizationContext] = None,
    ) -> List[Dict[str, Any]]:
        """使用 pgvector 的 cosine distance 進行語意檢索（Phase 0：ACL-aware）。"""
        from app.tasks.document_tasks import embed_texts

        db = SessionLocal()
        try:
            # 1. 取得查詢向量（Ollama / Voyage 自動切換）
            query_embedding = embed_texts([query], input_type="query")[0]

            # 2. 使用 pgvector cosine distance 搜尋
            query_obj = (
                db.query(
                    DocumentChunk,
                    DocumentChunk.embedding.cosine_distance(query_embedding).label("distance"),
                )
                .join(Document, DocumentChunk.document_id == Document.id)
                .filter(
                    DocumentChunk.tenant_id == tenant_id,
                    DocumentChunk.embedding.isnot(None),
                    Document.tombstoned_at.is_(None),  # Phase 0: 排除已標記刪除的文件
                )
            )

            # Phase 0: 部門 ACL 過濾
            if authz:
                query_obj = self._apply_department_acl_filter(query_obj, authz)
                query_obj = self._apply_source_acl_filter(query_obj, tenant_id, authz, db)

            # ── filter_dict：metadata 過濾 ──
            if filter_dict:
                for key, value in filter_dict.items():
                    if isinstance(value, list):
                        query_obj = query_obj.filter(
                            DocumentChunk.metadata_json[key].astext.in_(
                                [str(v) for v in value]
                            )
                        )
                    else:
                        query_obj = query_obj.filter(
                            DocumentChunk.metadata_json[key].astext == str(value)
                        )

            query_obj = (
                query_obj
                .order_by(DocumentChunk.embedding.cosine_distance(query_embedding))
                .limit(top_k)
            )

            results = []
            doc_map: Dict[UUID, str] = {}
            for chunk, distance in query_obj.all():
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
        authz: Optional[AuthorizationContext] = None,
    ) -> List[Dict[str, Any]]:
        """使用 BM25 在 DB chunks 上做關鍵字檢索（Phase 0：ACL-aware）。"""
        if not _HAS_BM25:
            logger.warning("rank_bm25 未安裝，關鍵字檢索不可用")
            return []

        try:
            db = SessionLocal()
            try:
                # Phase 0: JOIN Document 做 ACL 過濾
                chunks_q = (
                    db.query(DocumentChunk)
                    .join(Document, DocumentChunk.document_id == Document.id)
                    .filter(
                        DocumentChunk.tenant_id == tenant_id,
                        Document.tombstoned_at.is_(None),
                    )
                )
                # Phase 0: 部門 ACL 過濾
                if authz:
                    chunks_q = self._apply_department_acl_filter(chunks_q, authz)
                    chunks_q = self._apply_source_acl_filter(chunks_q, tenant_id, authz, db)
                chunks = chunks_q.all()

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
        authz: Optional[AuthorizationContext] = None,
    ) -> List[Dict[str, Any]]:
        """
        混合檢索：語意 + BM25，使用 Reciprocal Rank Fusion (RRF) 合併。
        Phase 0：傳遞 authz 到子檢索方法。
        """
        semantic_results = self._semantic_search(
            tenant_id, semantic_query, top_k=top_k, filter_dict=filter_dict, authz=authz,
        )
        keyword_results = self._keyword_search(tenant_id, keyword_query, top_k=top_k, authz=authz)

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

        # Rerank 需要 Voyage client；若未啟用則使用本地關鍵字感知重排序
        if self.voyage_client is None:
            return self._local_rerank(query, results, top_k=top_k)

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
    # 本地重排序（Voyage 不可用時的 fallback）
    # ─────────────────────────────────────────────

    def _local_rerank(
        self,
        query: str,
        results: List[Dict[str, Any]],
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        本地關鍵字感知重排序器。

        結合三項訊號重新計算分數：
          1. 原始 RRF / 語意分數（40%）
          2. jieba 詞級關鍵字重疊率（35%）
          3. 實體（人名 / 員工編號 / 檔名）精確匹配加分（25%）

        不需任何外部 API，零延遲。
        """
        if not results:
            return results

        query_tokens = set(self._tokenize(query))
        # 提取查詢中的人名 / 員工編號 / 關鍵實體
        query_entities: List[str] = []
        # 中文姓名（2~3 字）
        for name_match in re.finditer(r'[\u4e00-\u9fff]{2,4}', query):
            candidate = name_match.group()
            if candidate not in ('什麼', '多少', '如何', '可以', '是否', '哪些',
                                 '怎麼', '目前', '現在', '需要', '公司', '員工',
                                 '今年', '年度', '等級', '部門', '超過', '金額',
                                 '結果', '代表', '上限', '其中'):
                query_entities.append(candidate)
        # 員工編號 E001~E999
        for eid_match in re.finditer(r'E\d{3}', query, re.IGNORECASE):
            query_entities.append(eid_match.group().upper())

        scored: List[tuple] = []
        max_rrf = max((r.get('score', 0) for r in results), default=1.0) or 1.0

        for r in results:
            content = r.get('content', '')
            filename = r.get('filename', '')
            full_text = content + ' ' + filename

            # (1) 原始分數正規化 0~1
            rrf_norm = r.get('score', 0) / max_rrf

            # (2) 詞級關鍵字重疊率
            content_tokens = set(self._tokenize(full_text))
            if query_tokens:
                overlap = len(query_tokens & content_tokens) / len(query_tokens)
            else:
                overlap = 0.0

            # (3) 實體匹配加分
            entity_score = 0.0
            if query_entities:
                matches = sum(1 for e in query_entities if e in full_text)
                entity_score = matches / len(query_entities)

            # 綜合分數
            final = 0.40 * rrf_norm + 0.35 * overlap + 0.25 * entity_score
            scored.append((final, r))

        # 按重排分數降序排列
        scored.sort(key=lambda x: x[0], reverse=True)

        reranked_results: List[Dict[str, Any]] = []
        for final_score, r in scored[:top_k]:
            item = r.copy()
            item['score'] = round(final_score, 4)
            item['reranked'] = True
            reranked_results.append(item)

        logger.info(f"本地重排序完成：{len(results)} → {len(reranked_results)} 筆")
        return reranked_results

    # ─────────────────────────────────────────────
    # Redis 快取（Phase 0：ACL-aware）
    # ─────────────────────────────────────────────

    _CACHE_TTL = 300  # 5 分鐘

    def _cache_key(
        self,
        tenant_id: UUID,
        query: str,
        mode: str,
        top_k: int,
        min_score: float,
        authz: Optional[AuthorizationContext] = None,
    ) -> str:
        """
        ACL-aware 快取鍵。

        包含 policy_fingerprint，確保：
          - 不同使用者的快取不會互相洩漏
          - 權限變更後舊快取自動失效
        """
        auth_fragment = authz.to_cache_fragment() if authz else "auth:anon"
        epoch = self._acl_epoch(tenant_id)
        raw = f"{tenant_id}:{auth_fragment}:epoch:{epoch}:{query}:{mode}:{top_k}:{min_score}"
        h = hashlib.sha256(raw.encode()).hexdigest()[:16]
        return f"kb:search:{tenant_id}:{auth_fragment}:{h}"

    def _cache_get(
        self,
        tenant_id: UUID,
        query: str,
        mode: str,
        top_k: int,
        min_score: float,
        authz: Optional[AuthorizationContext] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        if not self._redis:
            return None
        try:
            key = self._cache_key(tenant_id, query, mode, top_k, min_score, authz)
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
        authz: Optional[AuthorizationContext] = None,
    ):
        if not self._redis:
            return
        try:
            key = self._cache_key(tenant_id, query, mode, top_k, min_score, authz)
            self._redis.setex(key, self._CACHE_TTL, json.dumps(results, default=str))
        except Exception:
            pass

    def invalidate_cache(self, tenant_id: UUID, policy_fingerprint: Optional[str] = None):
        """
        精確失效檢索快取。

        計畫不變量：必須提供 policy_fingerprint；禁止掃描並刪除整個租戶 cache。
        若未提供 fingerprint，改以 tenant 級 revision bump key 讓舊鍵自然 miss。
        """
        if not self._redis:
            return
        try:
            if policy_fingerprint:
                pattern = f"kb:search:{tenant_id}:auth:{policy_fingerprint}:*"
                cursor = 0
                while True:
                    cursor, keys = self._redis.scan(cursor, match=pattern, count=100)
                    if keys:
                        self._redis.delete(*keys)
                    if cursor == 0:
                        break
                return
            # 無 fingerprint：bump ACL epoch，舊鍵因 epoch 不匹配而失效（不 scan 全租戶）
            epoch_key = f"kb:acl_epoch:{tenant_id}"
            self._redis.incr(epoch_key)
        except Exception:
            pass

    def _acl_epoch(self, tenant_id: UUID) -> str:
        if not self._redis:
            return "0"
        try:
            return str(self._redis.get(f"kb:acl_epoch:{tenant_id}") or "0")
        except Exception:
            return "0"

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
