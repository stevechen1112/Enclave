import os
import hashlib
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List
from uuid import UUID
import httpx
from app.celery_app import celery_app
from app.config import settings
from app.db.session import SessionLocal
from app.crud import crud_document
from app.services.document_parser import DocumentParser, TextChunker
from app.services.deployment_mode import resolve_runtime_profiles_no_db
from app.schemas.document import DocumentUpdate
from app.models.document import DocumentChunk, DocumentChunk as DChunk  # alias for task use

logger = logging.getLogger(__name__)


# ── Embedding helpers ────────────────────────────────────────────────────────

def _embed_voyage(texts: List[str], model: str, input_type: str = "document") -> List[List[float]]:
    """Cloud embedding via Voyage AI API."""
    import voyageai
    client = voyageai.Client(api_key=settings.VOYAGE_API_KEY)
    all_embeddings: List[List[float]] = []
    batch_size = 32
    for i in range(0, len(texts), batch_size):
        result = client.embed(texts[i:i + batch_size], model=model, input_type=input_type)
        all_embeddings.extend(result.embeddings)
        time.sleep(0.5)
    return all_embeddings


def _embed_ollama(texts: List[str], model: str, _input_type: str = "document") -> List[List[float]]:
    """Local embedding via Ollama /api/embed endpoint (bge-m3 etc.)."""
    url = f"{settings.OLLAMA_EMBED_URL}/api/embed"
    all_embeddings: List[List[float]] = []
    batch_size = 16  # Ollama handles batch natively
    with httpx.Client(timeout=120.0) as client:
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            resp = client.post(url, json={"model": model, "input": batch})
            resp.raise_for_status()
            all_embeddings.extend(resp.json()["embeddings"])
    return all_embeddings


def embed_texts(texts: List[str], input_type: str = "document") -> List[List[float]]:
    """Route to the configured embedding provider."""
    runtime = resolve_runtime_profiles_no_db()
    embed_cfg = runtime.get("embedding", {})
    provider = str(embed_cfg.get("provider", getattr(settings, "EMBEDDING_PROVIDER", "voyage"))).lower()
    model = str(embed_cfg.get("model", settings.VOYAGE_MODEL if provider == "voyage" else settings.OLLAMA_EMBED_MODEL))
    if provider == "ollama":
        return _embed_ollama(texts, model, input_type)
    else:
        if not settings.VOYAGE_API_KEY:
            raise ValueError("VOYAGE_API_KEY 未設定（或改用 EMBEDDING_PROVIDER=ollama）")
        return _embed_voyage(texts, model, input_type)


@celery_app.task(bind=True, max_retries=3)
def process_document_task(self, document_id: str, file_path: str, tenant_id: str):
    """
    背景任務：處理文件
    1. 解析文件（LlamaParse 優先 → 內建解析器 fallback）
    2. 切片
    3. 向量化（Voyage voyage-4-lite）
    4. 寫入 pgvector（PostgreSQL）
    """
    db = SessionLocal()

    try:
        # ADR-012：task session 立即設定租戶 context（enforce 階段的最後防線）
        from app.services.rls import apply_rls_context
        apply_rls_context(db, UUID(tenant_id))

        # 1. 獲取文件記錄
        doc = crud_document.get(db, document_id=UUID(document_id))
        if not doc:
            raise ValueError("文件不存在")
        
        # 2. 更新狀態：解析中
        crud_document.update(
            db,
            db_obj=doc,
            obj_in=DocumentUpdate(status="parsing")
        )
        
        # 3. 解析文件（capability router: native / RAGFlow）
        # ADR-011：s3:// content_uri 先經後端下載到暫存再解析；本機路徑直接使用
        parse_path = file_path
        _tmp_download = None
        if str(file_path).startswith("s3://"):
            import tempfile
            from app.services.storage import get_storage_backend, parse_s3_uri

            _, storage_key = parse_s3_uri(file_path)
            # 防禦性檢查：key 的租戶前綴必須與 task 租戶一致——
            # RLS 只約束 DB，擋不住物件儲存層的跨租戶 key 讀取
            from app.services.storage import assert_key_matches_tenant
            assert_key_matches_tenant(storage_key, tenant_id)
            suffix = os.path.splitext(storage_key)[1] or ".bin"
            fd, _tmp_download = tempfile.mkstemp(prefix="enclave-dl-", suffix=suffix)
            os.close(fd)
            get_storage_backend().get_to_file(storage_key, _tmp_download)
            parse_path = _tmp_download
        try:
            from app.services.parse_pipeline import parse_document
            text_content, metadata, artifact = parse_document(
                parse_path, doc.file_type or "txt",
                document_id=UUID(document_id),
                revision=doc.version or 1,
                tenant_id=UUID(tenant_id),
            )
            # 儲存 ParseArtifact 到 document_artifacts
            from app.models.knowledge_base import DocumentArtifact
            db.add(DocumentArtifact(
                document_id=UUID(document_id),
                revision=doc.version or 1,
                artifact_type="parse",
                provider=artifact.parser.split("/")[0] if "/" in artifact.parser else "enclave",
                provider_version=artifact.version,
                checksum=artifact.source_hash,
                status="active",
                metadata_json=artifact.model_dump(),
            ))
            if artifact.source_hash:
                doc.content_hash = artifact.source_hash
            db.flush()
        except Exception as e:
            crud_document.update(
                db,
                db_obj=doc,
                obj_in=DocumentUpdate(
                    status="failed",
                    error_message=f"解析失敗: {str(e)}"
                )
            )
            if self.request.retries < self.max_retries:
                raise self.retry(exc=e, countdown=60)
            return {"status": "failed", "error": str(e)}
        finally:
            if _tmp_download and os.path.exists(_tmp_download):
                try:
                    os.remove(_tmp_download)
                except OSError:
                    pass
        
        # 3.5 儲存品質報告
        crud_document.update(
            db,
            db_obj=doc,
            obj_in=DocumentUpdate(quality_report=metadata)
        )
        
        # 4. 切片（結構化表格優先全量入庫）
        full_table_ok = doc.file_type in {"csv", "xlsx", "xls"}
        if full_table_ok and len(text_content) <= settings.TABLE_FULL_CHUNK_MAX_CHARS:
            chunks = [text_content.strip()]
        else:
            chunks = TextChunker.split_by_tokens(
                text_content,
                chunk_size=settings.CHUNK_SIZE,
                chunk_overlap=settings.CHUNK_OVERLAP
            )
        
        # 4.5 小檔案 fallback：若文字有效但太短無法分割，整段作為一個 chunk
        if not chunks and text_content.strip():
            chunks = [text_content.strip()]
        
        if not chunks:
            crud_document.update(
                db,
                db_obj=doc,
                obj_in=DocumentUpdate(
                    status="failed",
                    error_message="文件切片後無有效內容"
                )
            )
            return {"status": "failed", "error": "No valid chunks"}
        
        # 5. 更新狀態：向量化中
        crud_document.update(
            db,
            db_obj=doc,
            obj_in=DocumentUpdate(
                status="embedding",
                chunk_count=len(chunks)
            )
        )
        
        # 6. 向量化（Ollama bge-m3 本地 / Voyage cloud — 由 EMBEDDING_PROVIDER 決定）
        all_embeddings = embed_texts(chunks, input_type="document")
        
        # 7. 寫入 pgvector（直接儲存到 PostgreSQL）—— 含去重
        # Pre-fetch existing chunk hashes for this document in one query (avoids N+1)
        existing_hashes = {
            row.chunk_hash
            for row in db.query(DChunk.chunk_hash).filter(
                DChunk.document_id == UUID(document_id),
                DChunk.document_revision == int(doc.version or 1),
            ).all()
        }

        inserted = 0
        skipped = 0
        inserted_chunks = []
        for idx, (chunk, embedding) in enumerate(zip(chunks, all_embeddings)):
            chunk_hash = hashlib.sha256(chunk.encode()).hexdigest()[:16]
            vector_id = f"{document_id}-chunk-{idx}"

            # 去重：使用預先查詢的雜湊集合，避免 N+1 查詢
            if chunk_hash in existing_hashes:
                skipped += 1
                continue

            # 為 chunk 加入檔名前綴以增強檢索關聯性
            chunk_with_prefix = f"【{doc.filename}】\n{chunk}" if idx == 0 or len(chunk) < 800 else chunk

            db_chunk = DChunk(
                document_id=UUID(document_id),
                tenant_id=UUID(tenant_id),
                document_revision=int(doc.version or 1),
                chunk_index=idx,
                text=chunk_with_prefix,
                chunk_hash=chunk_hash,
                vector_id=vector_id,
                embedding=embedding,
                metadata_json={
                    "filename": doc.filename,
                    "chunk_index": idx,
                    "parse_engine": metadata.get("parse_engine", "native"),
                    "quality_score": metadata.get("quality_score", 0),
                    "tables_detected": metadata.get("tables_detected", 0),
                    "ocr_used": metadata.get("ocr_used", False),
                }
            )
            db.add(db_chunk)
            inserted_chunks.append(db_chunk)
            inserted += 1
        db.flush()
        from app.services.lexical_index import upsert_chunks as upsert_lexical_chunks
        upsert_lexical_chunks(db, inserted_chunks, doc)
        db.commit()
        
        if skipped:
            logger.info(f"去重: 跳過 {skipped} 個重複 chunk，寫入 {inserted} 個")
        
        # 8. 狀態 completed 與 outbox document_processed 必須同一交易
        from app.services.outbox_events import publish_event
        doc.status = "completed"
        doc.chunk_count = inserted
        doc.quality_report = metadata
        # ADR-008：catalog 粒度 genre 標註；標註失敗不得擋住入庫
        try:
            from app.services.genre_tagger import tag_document
            tag_document(doc, content_sample=text_content[:2000])
        except Exception as genre_exc:
            logger.warning("genre tagging failed (non-blocking): %s", genre_exc)
        # K1: processing success is not the same as answer readiness.  Profile
        # creation is part of the completion transaction and therefore cannot
        # silently fail for an active document.
        from app.services.document_profile import upsert_document_profile
        profile_row = upsert_document_profile(db, doc, text_content, metadata)
        if doc.file_type in {"csv", "xlsx", "xls"}:
            from app.services.structured_projection import upsert_structured_projection
            upsert_structured_projection(db, doc, text_content)
        if (profile_row.capability_readiness or {}).get("procedure"):
            from app.services.procedure_projection import project_procedure
            project_procedure(db, doc, text_content)
        # F4：跨語條款投影（非阻塞；失敗不影響 completed）
        try:
            from app.services.clause_projection import needs_clause_projection
            if needs_clause_projection(doc.filename or "", text_content[:2000]):
                import asyncio
                import openai as _openai
                from app.services.clause_projection import (
                    extract_clauses_with_llm,
                    upsert_clause_projection,
                )
                provider = str(getattr(settings, "LLM_PROVIDER", "openai")).lower()
                client = None
                model = ""
                if provider == "gemini" and getattr(settings, "GEMINI_API_KEY", ""):
                    client = _openai.AsyncOpenAI(
                        api_key=settings.GEMINI_API_KEY,
                        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                    )
                    model = getattr(settings, "GEMINI_MODEL", "gemini-3-flash-preview")
                elif provider == "openai" and getattr(settings, "OPENAI_API_KEY", ""):
                    client = _openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
                    model = getattr(settings, "OPENAI_MODEL", "gpt-4o")
                if client and model:
                    clauses = asyncio.run(
                        extract_clauses_with_llm(
                            text_content,
                            llm_client=client,
                            model=model,
                        )
                    )
                    upsert_clause_projection(
                        db=db,
                        document_id=doc.id,
                        revision=doc.version or 1,
                        clauses=clauses,
                        source_chars=len(text_content or ""),
                    )
                    logger.info(
                        "clause_projection built for %s: %s clauses",
                        doc.filename,
                        len(clauses),
                    )
        except Exception as proj_exc:
            logger.warning("clause projection failed (non-blocking): %s", proj_exc)
        db.add(doc)
        payload = {
            "filename": doc.filename,
            "file_type": doc.file_type,
            "tenant_id": tenant_id,
            "chunk_count": inserted,
            "parse_engine": metadata.get("parse_engine", "native"),
            "content_hash": doc.content_hash,
            "file_path": doc.file_path,
            "content_uri": doc.file_path,
            "uploaded_by": str(doc.uploaded_by) if doc.uploaded_by else None,
            "ragflow_already_ingested": bool(metadata.get("ragflow_already_ingested")),
            "ragflow_doc_ids": list(metadata.get("ragflow_doc_ids") or []),
        }
        # ADR-013：sidecar 歸屬以 tenant_sidecar_binding 為唯一權威
        from app.services.sidecar_binding import (
            resolve_ragflow_dataset_id,
            resolve_weknora_kb_id,
        )
        dataset_id = resolve_ragflow_dataset_id(db, UUID(tenant_id))
        if dataset_id:
            payload["dataset_id"] = dataset_id
        kb_id = resolve_weknora_kb_id(db, UUID(tenant_id))
        if kb_id:
            payload["kb_id"] = kb_id
        # DD-H09：parse 已寫入 RAGFlow 時先登記 mapping，outbox 只 reconcile
        if payload["ragflow_already_ingested"] and payload["ragflow_doc_ids"]:
            try:
                from app.gateway.resource_registry import ResourceRegistry
                from app.models.outbox import ProjectionStatus
                rid = str(payload["ragflow_doc_ids"][0])
                ResourceRegistry().upsert_mapping(
                    db,
                    enclave_resource_type="document",
                    enclave_resource_id=document_id,
                    enclave_revision=doc.version or 1,
                    provider="ragflow",
                    provider_resource_id=rid,
                    provider_revision=doc.version or 1,
                    checksum=doc.content_hash,
                    state="pending",
                )
                existing = (
                    db.query(ProjectionStatus)
                    .filter(
                        ProjectionStatus.resource_type == "document",
                        ProjectionStatus.resource_id == document_id,
                        ProjectionStatus.provider == "ragflow",
                    )
                    .first()
                )
                if existing:
                    existing.state = "pending"
                    existing.desired_revision = doc.version or 1
                else:
                    db.add(
                        ProjectionStatus(
                            resource_type="document",
                            resource_id=document_id,
                            provider="ragflow",
                            desired_revision=doc.version or 1,
                            applied_revision=0,
                            state="pending",
                        )
                    )
            except Exception as exc:
                logger.warning("ragflow parse mapping upsert failed: %s", exc)
        publish_event(
            db,
            aggregate_type="document",
            aggregate_id=document_id,
            event_type="document_processed",
            revision=doc.version or 1,
            payload=payload,
        )
        db.commit()

        # 8.6 清除租戶檢索快取（新文件上傳後失效舊快取）
        try:
            from app.services.kb_retrieval import KnowledgeBaseRetriever
            KnowledgeBaseRetriever().invalidate_cache(UUID(tenant_id))
        except Exception:
            pass

        return {
            "status": "completed",
            "document_id": document_id,
            "chunks": inserted,
        }
        
    except Exception as e:
        # 記錄錯誤
        if db:
            doc = crud_document.get(db, document_id=UUID(document_id))
            if doc:
                crud_document.update(
                    db,
                    db_obj=doc,
                    obj_in=DocumentUpdate(
                        status="failed",
                        error_message=str(e)
                    )
                )
        
        # 重試機制
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=60)
        
        return {"status": "failed", "error": str(e)}
    
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=2)
def process_url_task(self, document_id: str, url: str, tenant_id: str):
    """
    背景任務：擷取網頁 URL 內容並向量化。

    流程：
    1. 使用 trafilatura 擷取網頁正文
    2. 切片
    3. 向量化
    4. 寫入 pgvector
    """
    db = SessionLocal()

    try:
        doc = crud_document.get(db, document_id=UUID(document_id))
        if not doc:
            raise ValueError("文件記錄不存在")

        crud_document.update(
            db, db_obj=doc,
            obj_in=DocumentUpdate(status="parsing"),
        )

        # 1. 擷取網頁
        try:
            text_content, metadata = DocumentParser.parse_url(url)
        except Exception as e:
            crud_document.update(
                db, db_obj=doc,
                obj_in=DocumentUpdate(status="failed", error_message=f"網頁擷取失敗: {e}"),
            )
            if self.request.retries < self.max_retries:
                raise self.retry(exc=e, countdown=60)
            return {"status": "failed", "error": str(e)}

        crud_document.update(
            db, db_obj=doc,
            obj_in=DocumentUpdate(quality_report=metadata),
        )

        # 2. 切片
        chunks = TextChunker.split_by_tokens(
            text_content,
            chunk_size=settings.CHUNK_SIZE,
            chunk_overlap=settings.CHUNK_OVERLAP,
        )

        if not chunks:
            crud_document.update(
                db, db_obj=doc,
                obj_in=DocumentUpdate(status="failed", error_message="網頁內容切片後無有效內容"),
            )
            return {"status": "failed", "error": "No valid chunks from URL"}

        crud_document.update(
            db, db_obj=doc,
            obj_in=DocumentUpdate(status="embedding", chunk_count=len(chunks)),
        )

        # 3. 向量化（統一走 embed_texts 路由，依 EMBEDDING_PROVIDER 決定 Ollama 或 Voyage）
        batch_size = 32
        all_embeddings = []

        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            batch_embs = embed_texts(batch)
            all_embeddings.extend(batch_embs)
            time.sleep(0.1)

        # 4. 寫入 pgvector（含去重）
        # Pre-fetch existing hashes in one query (avoids N+1)
        existing_hashes = {
            row.chunk_hash
            for row in db.query(DChunk.chunk_hash).filter(
                DChunk.document_id == UUID(document_id),
                DChunk.document_revision == int(doc.version or 1),
            ).all()
        }

        inserted = 0
        inserted_chunks = []
        for idx, (chunk, embedding) in enumerate(zip(chunks, all_embeddings)):
            chunk_hash = hashlib.sha256(chunk.encode()).hexdigest()[:16]

            # 去重：使用預先查詢的雜湊集合
            if chunk_hash in existing_hashes:
                continue

            db_chunk = DChunk(
                document_id=UUID(document_id),
                tenant_id=UUID(tenant_id),
                document_revision=int(doc.version or 1),
                chunk_index=idx,
                text=chunk,
                chunk_hash=chunk_hash,
                vector_id=f"{document_id}-url-chunk-{idx}",
                embedding=embedding,
                metadata_json={
                    "filename": doc.filename,
                    "source_url": url,
                    "chunk_index": idx,
                    "parse_engine": "trafilatura",
                },
            )
            db.add(db_chunk)
            inserted_chunks.append(db_chunk)
            inserted += 1
        db.flush()
        from app.services.lexical_index import upsert_chunks as upsert_lexical_chunks
        upsert_lexical_chunks(db, inserted_chunks, doc)
        db.commit()

        # completed + document_processed 同一交易（與 process_document_task 對齊）
        from app.services.outbox_events import publish_event
        doc.status = "completed"
        doc.chunk_count = inserted
        doc.quality_report = metadata
        from app.services.document_profile import upsert_document_profile
        upsert_document_profile(
            db,
            doc,
            text_content,
            {**(metadata or {}), "parse_engine": "trafilatura", "ocr_used": False},
        )
        db.add(doc)
        publish_event(
            db,
            aggregate_type="document",
            aggregate_id=document_id,
            event_type="document_processed",
            revision=doc.version or 1,
            payload={
                "filename": doc.filename,
                "file_type": doc.file_type or "html",
                "tenant_id": tenant_id,
                "chunk_count": inserted,
                "parse_engine": "trafilatura",
                "content_hash": doc.content_hash,
                "file_path": doc.file_path,
                "content_uri": url,
                "source_url": url,
                "uploaded_by": str(doc.uploaded_by) if doc.uploaded_by else None,
            },
        )
        db.commit()

        # 清除快取
        try:
            from app.services.kb_retrieval import KnowledgeBaseRetriever
            retriever = KnowledgeBaseRetriever()
            retriever.invalidate_cache(UUID(tenant_id))
        except Exception:
            pass

        return {
            "status": "completed",
            "document_id": document_id,
            "url": url,
            "chunks": inserted,
        }

    except Exception as e:
        if db:
            doc = crud_document.get(db, document_id=UUID(document_id))
            if doc:
                crud_document.update(
                    db, db_obj=doc,
                    obj_in=DocumentUpdate(status="failed", error_message=str(e)),
                )
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=60)
        return {"status": "failed", "error": str(e)}

    finally:
        db.close()


# ─────────────────────────────────────────────────────────────
# P10-1 File Watcher 專用任務
# ─────────────────────────────────────────────────────────────

@celery_app.task(bind=True, max_retries=3, name="tasks.watcher_ingest_file")
def watcher_ingest_file_task(
    self,
    file_path: str,
    tenant_id: str,
    user_id: str,
    skip_if_current: bool = False,
    skip_review: bool = False,
):
    """
    File Watcher 觸發的文件索引任務。

    - 新檔案：建立 Document 記錄，觸發 process_document_task
    - 修改檔案：刪除舊 chunks，重新索引
    - skip_if_current=True：若已索引且 file mtime 沒變，直接跳過（初始掃描用）
    - skip_review=True：審核通過後入庫，略過再進 review queue（DD-H12）
    """
    db = SessionLocal()
    try:
        path = Path(file_path)
        if not path.exists():
            return {"status": "skipped", "reason": "file_not_found", "path": file_path}

        from app.models.document import Document

        filename = path.name
        ext = path.suffix.lower().lstrip(".") or "bin"
        file_size = path.stat().st_size
        file_mtime = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)

        # 查詢是否已有此路徑的 Document 記錄
        existing = (
            db.query(Document)
            .filter(
                Document.tenant_id == UUID(tenant_id),
                Document.file_path == str(path),
            )
            .first()
        )

        if existing:
            # skip_if_current：比較 updated_at vs file mtime（已撤銷不可視為 current）
            if (
                skip_if_current
                and existing.status == "completed"
                and existing.tombstoned_at is None
            ):
                if existing.updated_at and existing.updated_at >= file_mtime:
                    return {
                        "status": "skipped",
                        "reason": "already_current",
                        "document_id": str(existing.id),
                    }

        # DD-H12：watcher → classifier → enqueue；核准後以 skip_review 入庫
        review_enabled = os.getenv("REVIEW_QUEUE_ENABLED", "true").lower() == "true"
        if review_enabled and not skip_review:
            import asyncio
            from app.agent.classifier import get_classifier
            from app.agent.review_queue import ReviewQueueManager

            # 既有可搜尋文件標記 pending_review；保留舊 revision chunks 供
            # 已發布 KB revision 稽核與重建，status 會阻止它們進一般檢索。
            if existing and existing.tombstoned_at is None:
                existing.status = "pending_review"
                existing.error_message = "awaiting_review"
                existing.chunk_count = 0
                db.commit()
                try:
                    from app.services.kb_retrieval import KnowledgeBaseRetriever
                    KnowledgeBaseRetriever().invalidate_cache(UUID(tenant_id))
                except Exception:
                    pass

            proposal = asyncio.run(get_classifier().classify_file(path))
            review_id = ReviewQueueManager(db).enqueue(proposal, UUID(tenant_id))
            logger.info(
                "[WatcherTask] queued for review: %s review_id=%s confidence=%.2f",
                filename,
                review_id,
                proposal.confidence_score,
            )
            return {
                "status": "queued_for_review",
                "review_item_id": review_id,
                "filename": filename,
                "needs_review": proposal.needs_review,
                "confidence_score": proposal.confidence_score,
                "stale_index_cleared": bool(existing),
            }

        if existing:
            # 修改／撤銷後重入庫：建立新 revision，舊 chunks 不可原地刪除。
            if existing.tombstoned_at is not None:
                existing.tombstoned_at = None
                try:
                    from app.gateway.authorization import get_gateway_authorizer
                    get_gateway_authorizer().clear_resource_deny(str(existing.id))
                except Exception as exc:
                    logger.warning("[WatcherTask] clear deny after restore failed: %s", exc)
            existing.version = int(existing.version or 1) + 1
            existing.status = "uploading"
            existing.error_message = None
            existing.chunk_count = None
            existing.file_size = file_size
            db.commit()
            doc_id = str(existing.id)
            logger.info(f"[WatcherTask] 重新索引：{filename} (doc={doc_id})")
        else:
            # 新檔案：建立 Document 記錄
            from app.models.document import Document as DocModel

            doc = DocModel(
                tenant_id=UUID(tenant_id),
                uploaded_by=UUID(user_id) if user_id else None,
                filename=filename,
                file_type=ext,
                file_path=str(path),
                file_size=file_size,
                source_type="file",
                status="uploading",
            )
            db.add(doc)
            db.commit()
            db.refresh(doc)
            doc_id = str(doc.id)
            logger.info(f"[WatcherTask] 新檔案入庫：{filename} (doc={doc_id})")

        # 觸發完整的解析 + 向量化流程
        process_document_task.delay(doc_id, file_path, tenant_id)
        return {"status": "queued", "document_id": doc_id, "filename": filename}

    except Exception as exc:
        logger.error(f"[WatcherTask] 索引任務失敗 {file_path}: {exc}")
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=30)
        return {"status": "failed", "error": str(exc)}

    finally:
        db.close()


@celery_app.task(bind=True, max_retries=2, name="tasks.watcher_delete_file")
def watcher_delete_file_task(self, file_path: str, tenant_id: str):
    """
    File Watcher 偵測到刪除事件時，從知識庫移除對應記錄。

    查詢 file_path 欄位確認哪個 Document 代表這個檔案，
    刪除 Document 及所有關聯 chunks，並清除 KB 快取。
    """
    db = SessionLocal()
    try:
        from app.models.document import Document

        existing = (
            db.query(Document)
            .filter(
                Document.tenant_id == UUID(tenant_id),
                Document.file_path == file_path,
                Document.tombstoned_at.is_(None),
            )
            .first()
        )
        if not existing:
            logger.info(f"[WatcherTask] 已刪除（記錄不存在）：{file_path}")
            return {"status": "not_found", "path": file_path}

        doc_id = str(existing.id)
        from app.services.document_revocation import get_document_revocation

        actor_id = existing.uploaded_by or UUID(int=0)
        result = get_document_revocation().revoke(
            db,
            document_id=existing.id,
            actor_id=actor_id,
            tenant_id=UUID(tenant_id),
            reason="watcher_file_deleted",
        )
        if not result.get("ok"):
            logger.info(
                "[WatcherTask] revoke skipped: %s reason=%s",
                file_path,
                result.get("reason"),
            )
            return {"status": "not_found", "path": file_path, "reason": result.get("reason")}

        logger.info(f"[WatcherTask] 已從知識庫移除：{Path(file_path).name} (doc={doc_id})")

        return {"status": "deleted", "document_id": doc_id, "deny_first": True}

    except Exception as exc:
        logger.error(f"[WatcherTask] 刪除任務失敗 {file_path}: {exc}")
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=30)
        return {"status": "failed", "error": str(exc)}

    finally:
        db.close()
