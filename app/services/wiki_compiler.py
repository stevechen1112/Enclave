"""Phase 4 — Wiki compilation as derived projection."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.wiki import WikiPage, WikiRevision, WIKI_PAGE_TYPES
from app.services.outbox_events import publish_event

logger = logging.getLogger(__name__)


class WikiCompiler:
    async def _compile_via_weknora(
        self,
        kb_id: UUID,
        page_type: str,
    ) -> Optional[Dict[str, Any]]:
        if os.getenv("WEKNORA_ENABLED", "").lower() != "true":
            return None
        try:
            from app.gateway.adapters.weknora_http import WeKnoraHTTPAdapter
            from app.gateway.token_provider import build_weknora_token_provider
            adapter = WeKnoraHTTPAdapter(
                base_url=os.getenv("WEKNORA_BASE_URL", "http://weknora:8080"),
                api_key=os.getenv("WEKNORA_API_KEY", ""),
                token_provider=build_weknora_token_provider(),
            )
            await adapter.compile_wiki(kb_id)
            pages = await adapter.list_wiki_pages(kb_id)
            items = pages if isinstance(pages, list) else (
                (pages or {}).get("pages") or (pages or {}).get("data") or []
            )
            candidates = []
            for page in items:
                data = page.get("data", page)
                content = data.get("content", "")
                if not content or content.startswith("Auto-compiled"):
                    continue
                if page_type and page.get("page_type", page_type) != page_type:
                    continue
                candidates.append((page, data))
            if not candidates:
                return None
            # 優先 index 頁，否則取第一個有內容的頁面
            candidates.sort(key=lambda pd: 0 if "index" in str(pd[0].get("slug", "")) else 1)
            page, data = candidates[0]
            return {
                "content": data["content"],
                "citation_map": data.get("citations", data.get("citation_map", [])),
                "provider": "weknora",
                "title": page.get("title") or data.get("title") or "",
            }
        except Exception as exc:
            logger.warning("WeKnora wiki compile failed: %s", exc)
        return None

    def compile_kb(
        self,
        db: Session,
        tenant_id: UUID,
        kb_id: UUID,
        page_type: str = "summary",
        source_document_ids: Optional[List[str]] = None,
    ) -> WikiPage:
        if page_type not in WIKI_PAGE_TYPES:
            page_type = "summary"
        slug = f"{page_type}-{kb_id}"
        page = (
            db.query(WikiPage)
            .filter(WikiPage.tenant_id == tenant_id, WikiPage.slug == slug)
            .first()
        )
        if not page:
            page = WikiPage(
                tenant_id=tenant_id,
                kb_id=kb_id,
                slug=slug,
                title=f"{page_type} for KB",
                page_type=page_type,
                source_document_ids=source_document_ids or [],
                status="draft",
            )
            db.add(page)
            db.flush()

        revision_num = (page.active_revision or 0) + 1
        remote = asyncio.run(self._compile_via_weknora(kb_id, page_type))
        if not remote:
            # 禁止占位 published：標記 failed，不寫假內容
            page.status = "failed"
            page.source_document_ids = source_document_ids or page.source_document_ids or []
            publish_event(
                db,
                aggregate_type="wiki",
                aggregate_id=str(page.id),
                event_type="compile_failed",
                revision=revision_num,
                payload={"kb_id": str(kb_id), "page_type": page_type, "reason": "weknora_unavailable"},
            )
            db.commit()
            db.refresh(page)
            return page

        content = remote["content"]
        if remote.get("title"):
            page.title = remote["title"]
        citation_map = remote.get("citation_map") or [
            {"document_id": d, "revision": 1}
            for d in (source_document_ids or [])
        ]
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        rev = WikiRevision(
            wiki_page_id=page.id,
            revision=revision_num,
            content=content,
            content_hash=content_hash,
            citation_map=citation_map,
            compile_job_id=f"wiki-{page.id}-{revision_num}",
        )
        db.add(rev)
        page.active_revision = revision_num
        page.status = "published"
        page.source_document_ids = source_document_ids or page.source_document_ids or []

        publish_event(
            db,
            aggregate_type="wiki",
            aggregate_id=str(page.id),
            event_type="compiled",
            revision=revision_num,
            payload={"kb_id": str(kb_id), "page_type": page_type},
        )
        db.commit()
        db.refresh(page)
        return page

    def edit_page(
        self,
        db: Session,
        page: WikiPage,
        *,
        title: Optional[str] = None,
        content: Optional[str] = None,
        editor_id: Optional[str] = None,
    ) -> WikiPage:
        """管理員手動編輯：內容變更建立新 revision（保留 citation_map），
        標記 provenance 為 manual；重編譯仍會產生更新 revision，不覆寫歷史。"""
        if title and title != page.title:
            page.title = title
        current_rev = (
            db.query(WikiRevision)
            .filter(WikiRevision.wiki_page_id == page.id, WikiRevision.revision == page.active_revision)
            .first()
        )
        if content is not None and content != (current_rev.content if current_rev else ""):
            revision_num = (page.active_revision or 0) + 1
            rev = WikiRevision(
                wiki_page_id=page.id,
                revision=revision_num,
                content=content,
                content_hash=hashlib.sha256(content.encode()).hexdigest()[:16],
                citation_map=list(current_rev.citation_map) if current_rev and current_rev.citation_map else [],
                compile_job_id=f"manual-edit-{editor_id or 'unknown'}",
            )
            db.add(rev)
            page.active_revision = revision_num
        if page.status == "draft":
            page.status = "published"
        publish_event(
            db,
            aggregate_type="wiki",
            aggregate_id=str(page.id),
            event_type="edited",
            revision=page.active_revision or 1,
            payload={"editor_id": editor_id or "", "manual": True},
        )
        db.commit()
        db.refresh(page)
        return page

    def tombstone_page(self, db: Session, page_id: UUID) -> bool:
        page = db.query(WikiPage).filter(WikiPage.id == page_id).first()
        if not page:
            return False
        page.status = "tombstoned"
        page.tombstoned_at = datetime.now(timezone.utc)
        db.commit()
        return True

    def tombstone_by_source_document(
        self,
        db: Session,
        tenant_id: UUID,
        document_id: str,
        *,
        recompile: bool = True,
    ) -> Dict[str, int]:
        """
        撤權/刪除文件後：
        - 僅引用該文件 → tombstone
        - 另有其他來源 → 標記 stale、移除該來源，並嘗試重編譯
        """
        pages = (
            db.query(WikiPage)
            .filter(
                WikiPage.tenant_id == tenant_id,
                WikiPage.tombstoned_at.is_(None),
                WikiPage.status.in_(("published", "stale", "draft")),
            )
            .all()
        )
        tombstoned = 0
        stale = 0
        recompiled = 0
        for page in pages:
            src = [str(x) for x in (page.source_document_ids or [])]
            if document_id not in src:
                continue
            remaining = [x for x in src if x != document_id]
            if not remaining:
                page.status = "tombstoned"
                page.tombstoned_at = datetime.now(timezone.utc)
                page.source_document_ids = []
                tombstoned += 1
                publish_event(
                    db,
                    aggregate_type="wiki",
                    aggregate_id=str(page.id),
                    event_type="revoked",
                    revision=(page.active_revision or 0) + 1,
                    payload={"reason": "source_document_revoked", "document_id": document_id},
                )
            else:
                page.source_document_ids = remaining
                page.status = "stale"
                stale += 1
                publish_event(
                    db,
                    aggregate_type="wiki",
                    aggregate_id=str(page.id),
                    event_type="stale",
                    revision=(page.active_revision or 0) + 1,
                    payload={"reason": "source_document_revoked", "document_id": document_id},
                )
        if tombstoned or stale:
            db.commit()

        if recompile and stale and os.getenv("WEKNORA_ENABLED", "").lower() == "true":
            for page in (
                db.query(WikiPage)
                .filter(
                    WikiPage.tenant_id == tenant_id,
                    WikiPage.status == "stale",
                    WikiPage.tombstoned_at.is_(None),
                )
                .all()
            ):
                try:
                    self.compile_kb(
                        db,
                        tenant_id=tenant_id,
                        kb_id=page.kb_id,
                        page_type=page.page_type or "summary",
                        source_document_ids=page.source_document_ids or [],
                    )
                    recompiled += 1
                except Exception as exc:
                    logger.warning("wiki recompile after revoke failed page=%s: %s", page.id, exc)

        return {"tombstoned": tombstoned, "stale": stale, "recompiled": recompiled}

    def search_pages(
        self, db: Session, tenant_id: UUID, query: str, limit: int = 10,
    ) -> List[WikiPage]:
        return (
            db.query(WikiPage)
            .filter(
                WikiPage.tenant_id == tenant_id,
                WikiPage.status == "published",
                WikiPage.tombstoned_at.is_(None),
                WikiPage.title.ilike(f"%{query}%"),
            )
            .limit(limit)
            .all()
        )
