"""F4 — 跨語條款對照投影（入庫後結構化，非 prompt 猜測）。

對多語／條款型文件（如 ETI Base Code 緬甸文），在入庫完成後以強 LLM
產出「條款編號 → 原文摘錄 → 中／英標題／摘要」投影，寫入 DocumentArtifact
（artifact_type=clause_projection）。問答 intent=translate 時讀投影，
不得只靠 chat prompt 現場翻譯。
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Dict, List, Optional
from uuid import UUID

logger = logging.getLogger(__name__)

ARTIFACT_TYPE = "clause_projection"
PROVIDER = "enclave"

_CLAUSE_PROMPT = """你是文件結構化助理。下方是一份可能含非中文（例如緬甸文）的條款文件 OCR 文本。
請抽出所有可辨識的條款／條號，輸出 JSON 陣列，每筆格式：
{
  "clause_id": "1 或 1.1 等原文編號",
  "title_en": "英文標題（若頁面無英文則依內容意譯）",
  "title_zh": "繁體中文標題",
  "summary_zh": "該條款繁中摘要（1-3 句）",
  "source_excerpt": "原文摘錄（保留原語言，最多 200 字）"
}
只輸出 JSON 陣列，不要 markdown 圍欄或其他說明。
"""


def needs_clause_projection(filename: str, text_sample: str) -> bool:
    """啟發式：檔名／文本暗示跨語條款型文件時應建投影。"""
    name = (filename or "").casefold()
    sample = text_sample or ""
    if any(k in name for k in ("eti", "base-code", "base_code", "burmese", "myanmar")):
        return True
    # 緬甸文字元區
    if sum(1 for ch in sample[:2000] if "\u1000" <= ch <= "\u109f") >= 20:
        return True
    if re.search(r"(?i)base\s*code|clause\s*\d+", sample[:2000]):
        return True
    return False


def _parse_clauses_json(raw: str) -> List[Dict[str, Any]]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("clause projection must be a JSON array")
    out: List[Dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("clause_id") or "").strip()
        if not cid:
            continue
        out.append(
            {
                "clause_id": cid,
                "title_en": str(item.get("title_en") or "").strip(),
                "title_zh": str(item.get("title_zh") or "").strip(),
                "summary_zh": str(item.get("summary_zh") or "").strip(),
                "source_excerpt": str(item.get("source_excerpt") or "").strip()[:400],
            }
        )
    return out


async def extract_clauses_with_llm(text: str, *, llm_client, model: str) -> List[Dict[str, Any]]:
    """呼叫 LLM 產出條款對照；失敗拋例外由呼叫端決定重試／failed。"""
    content = (text or "")[:24000]
    # 部分模型（如 gpt-5.*）不接受 temperature=0；省略以用預設。
    resp = await llm_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _CLAUSE_PROMPT},
            {"role": "user", "content": content},
        ],
    )
    raw = resp.choices[0].message.content or ""
    return _parse_clauses_json(raw)


def upsert_clause_projection(
    *,
    db,
    document_id: UUID,
    revision: int,
    clauses: List[Dict[str, Any]],
    source_chars: int,
    sync_wiki: bool = True,
) -> Any:
    """寫入／更新 DocumentArtifact(clause_projection)；可選同步 Enclave Wiki。"""
    from app.models.knowledge_base import DocumentArtifact

    payload = {"clauses": clauses, "source_chars": source_chars, "schema": 1}
    checksum = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()

    existing = (
        db.query(DocumentArtifact)
        .filter(
            DocumentArtifact.document_id == document_id,
            DocumentArtifact.artifact_type == ARTIFACT_TYPE,
            DocumentArtifact.provider == PROVIDER,
            DocumentArtifact.status == "active",
        )
        .first()
    )
    if existing:
        existing.revision = revision
        existing.checksum = checksum
        existing.metadata_json = payload
        existing.status = "active"
        db.add(existing)
        art = existing
    else:
        art = DocumentArtifact(
            document_id=document_id,
            revision=revision,
            artifact_type=ARTIFACT_TYPE,
            provider=PROVIDER,
            provider_version="1.0",
            checksum=checksum,
            status="active",
            metadata_json=payload,
        )
        db.add(art)
    db.flush()
    if sync_wiki and clauses:
        try:
            sync_clause_projection_to_wiki(
                db=db,
                document_id=document_id,
                clauses=clauses,
            )
        except Exception as exc:
            logger.warning("wiki sync for clause projection failed (non-blocking): %s", exc)
    return art


def sync_clause_projection_to_wiki(
    *,
    db,
    document_id: UUID,
    clauses: List[Dict[str, Any]],
) -> Optional[Any]:
    """將條款投影寫入 Enclave Wiki（compiled 層），並對接編譯節奏。

    ADR-007：這是 Enclave Wiki 投影（provider=enclave），**不是** Neo4j 雙寫。
    若文件掛在 KB 且 WEKNORA_ENABLED，另發 wiki/compiled outbox 觸發 WeKnora 重編譯。
    """
    import hashlib as _hashlib
    import os

    from app.models.document import Document
    from app.models.wiki import WikiPage, WikiRevision
    from app.services.outbox_events import publish_event

    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        return None

    slug = f"clause-projection-{str(document_id)[:8]}"
    title = f"條款對照：{doc.filename}"
    body = format_projection_context(
        [{"filename": doc.filename, "document_id": str(doc.id), "clauses": clauses}]
    )
    content_hash = _hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]

    page = (
        db.query(WikiPage)
        .filter(WikiPage.tenant_id == doc.tenant_id, WikiPage.slug == slug)
        .first()
    )
    if not page:
        page = WikiPage(
            tenant_id=doc.tenant_id,
            kb_id=doc.knowledge_base_id,
            slug=slug,
            title=title,
            page_type="comparison",
            provider="enclave",
            source_document_ids=[str(document_id)],
            status="published",
            active_revision=0,
        )
        db.add(page)
        db.flush()
    else:
        page.title = title
        page.status = "published"
        page.tombstoned_at = None
        page.source_document_ids = [str(document_id)]
        page.kb_id = doc.knowledge_base_id or page.kb_id
        page.provider = "enclave"

    revision_num = (page.active_revision or 0) + 1
    rev = WikiRevision(
        wiki_page_id=page.id,
        revision=revision_num,
        content=body,
        content_hash=content_hash,
        citation_map=[
            {"document_id": str(document_id), "revision": doc.version or 1}
        ],
        compile_job_id=f"clause-projection-{revision_num}",
        status="active",
    )
    db.add(rev)
    page.active_revision = revision_num

    publish_event(
        db,
        aggregate_type="wiki",
        aggregate_id=str(page.id),
        event_type="clause_projection_synced",
        revision=revision_num,
        payload={
            "document_id": str(document_id),
            "clause_count": len(clauses),
            "provider": "enclave",
            "page_type": "comparison",
        },
    )
    # 編譯節奏：有 KB 且 WeKnora 開啟時觸發 sidecar 重編譯（ADR-007 邊界：不寫 Neo4j）
    if doc.knowledge_base_id and os.getenv("WEKNORA_ENABLED", "").lower() == "true":
        publish_event(
            db,
            aggregate_type="wiki",
            aggregate_id=str(page.id),
            event_type="compiled",
            revision=revision_num,
            payload={
                "kb_id": str(doc.knowledge_base_id),
                "page_type": "comparison",
                "source": "clause_projection",
            },
        )
    db.flush()
    return page


def load_clause_projections_for_query(
    *,
    db,
    tenant_id: UUID,
    query: str,
    limit: int = 3,
) -> List[Dict[str, Any]]:
    """translate 意圖：撈出相關文件的條款投影供 context 注入。"""
    from app.models.document import Document
    from app.models.knowledge_base import DocumentArtifact

    q = (query or "").casefold()
    arts = (
        db.query(DocumentArtifact, Document)
        .join(Document, Document.id == DocumentArtifact.document_id)
        .filter(
            Document.tenant_id == tenant_id,
            Document.status == "completed",
            Document.tombstoned_at.is_(None),
            DocumentArtifact.artifact_type == ARTIFACT_TYPE,
            DocumentArtifact.status == "active",
        )
        .all()
    )
    scored: List[tuple[float, Dict[str, Any]]] = []
    for art, doc in arts:
        name = (doc.filename or "").casefold()
        score = 0.0
        if "eti" in q and "eti" in name:
            score += 5
        if "base code" in q and "base" in name:
            score += 3
        if any(tok in name for tok in ("burmese", "myanmar", "eti")):
            score += 1
        meta = art.metadata_json or {}
        clauses = meta.get("clauses") or []
        if not clauses:
            continue
        scored.append(
            (
                score,
                {
                    "document_id": str(doc.id),
                    "filename": doc.filename,
                    "clauses": clauses,
                },
            )
        )
    scored.sort(key=lambda x: x[0], reverse=True)
    # 無關鍵字命中時仍回傳有投影的文件（最多 limit）
    if not any(s > 0 for s, _ in scored) and scored:
        return [item for _, item in scored[:limit]]
    return [item for s, item in scored if s > 0][:limit]


def format_projection_context(projections: List[Dict[str, Any]]) -> str:
    """組裝進 chat context_parts 的可讀條款對照。"""
    lines = ["【條款對照投影】"]
    for p in projections:
        lines.append(f"文件：{p.get('filename')}")
        for c in (p.get("clauses") or [])[:40]:
            cid = c.get("clause_id") or "?"
            zh = c.get("title_zh") or ""
            en = c.get("title_en") or ""
            summary = c.get("summary_zh") or ""
            lines.append(f"- {cid}. {zh}" + (f" / {en}" if en else ""))
            if summary:
                lines.append(f"  {summary}")
    return "\n".join(lines)

