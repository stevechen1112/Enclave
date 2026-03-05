import os
import hashlib
import time
import logging
from datetime import datetime
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
        
        # 3. 解析文件（自動選擇 LlamaParse 或內建解析器）
        try:
            text_content, metadata = DocumentParser.parse(file_path, doc.file_type)
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
                DChunk.document_id == UUID(document_id)
            ).all()
        }

        inserted = 0
        skipped = 0
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
            inserted += 1
        
        db.commit()
        
        if skipped:
            logger.info(f"去重: 跳過 {skipped} 個重複 chunk，寫入 {inserted} 個")
        
        # 8. 更新狀態：完成
        crud_document.update(
            db,
            db_obj=doc,
            obj_in=DocumentUpdate(
                status="completed",
                chunk_count=inserted,
                quality_report=metadata
            )
        )
        
        # 8.5 清除租戶檢索快取（新文件上傳後失效舊快取）
        try:
            from app.services.kb_retrieval import KnowledgeBaseRetriever
            retriever = KnowledgeBaseRetriever()
            retriever.invalidate_cache(UUID(tenant_id))
        except Exception:
            pass  # 快取清除失敗不影響主流程
        
        # 9. 清理臨時文件（可選）
        # os.remove(file_path)
        
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
                DChunk.document_id == UUID(document_id)
            ).all()
        }

        inserted = 0
        for idx, (chunk, embedding) in enumerate(zip(chunks, all_embeddings)):
            chunk_hash = hashlib.sha256(chunk.encode()).hexdigest()[:16]

            # 去重：使用預先查詢的雜湊集合
            if chunk_hash in existing_hashes:
                continue

            db_chunk = DChunk(
                document_id=UUID(document_id),
                tenant_id=UUID(tenant_id),
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
            inserted += 1

        db.commit()

        crud_document.update(
            db, db_obj=doc,
            obj_in=DocumentUpdate(
                status="completed",
                chunk_count=inserted,
                quality_report=metadata,
            ),
        )

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
):
    """
    File Watcher 觸發的文件索引任務。

    - 新檔案：建立 Document 記錄，觸發 process_document_task
    - 修改檔案：刪除舊 chunks，重新索引
    - skip_if_current=True：若已索引且 file mtime 沒變，直接跳過（初始掃描用）
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
        file_mtime = datetime.utcfromtimestamp(path.stat().st_mtime)

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
            # skip_if_current：比較 updated_at vs file mtime
            if skip_if_current and existing.status == "completed":
                if existing.updated_at and existing.updated_at >= file_mtime:
                    return {
                        "status": "skipped",
                        "reason": "already_current",
                        "document_id": str(existing.id),
                    }

            # 修改：清除舊 chunks，重新索引
            db.query(DocumentChunk).filter(
                DocumentChunk.document_id == existing.id
            ).delete(synchronize_session=False)
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
                uploaded_by=UUID(user_id),
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
            )
            .first()
        )
        if not existing:
            logger.info(f"[WatcherTask] 已刪除（記錄不存在）：{file_path}")
            return {"status": "not_found", "path": file_path}

        doc_id = str(existing.id)
        crud_document.delete(db, document_id=existing.id)
        logger.info(f"[WatcherTask] 已從知識庫移除：{Path(file_path).name} (doc={doc_id})")

        # 清除檢索快取
        try:
            from app.services.kb_retrieval import KnowledgeBaseRetriever
            KnowledgeBaseRetriever().invalidate_cache(UUID(tenant_id))
        except Exception:
            pass

        return {"status": "deleted", "document_id": doc_id}

    except Exception as exc:
        logger.error(f"[WatcherTask] 刪除任務失敗 {file_path}: {exc}")
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=30)
        return {"status": "failed", "error": str(exc)}

    finally:
        db.close()
