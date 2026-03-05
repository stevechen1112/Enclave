"""
Phase 11 — 內容生成 API

  POST /generate/stream      — SSE 串流生成（主要端點）
  POST /generate/export/docx — 匯出 Word
  POST /generate/export/pdf  — 匯出 PDF
  GET  /generate/templates   — 可用生成模板清單
"""

import json
import logging
from typing import List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse, Response
from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, get_db
from app.services.content_generator import ContentGenerator, GenerationTemplate
from app.services.kb_retrieval import KnowledgeBaseRetriever
from app.services.llm_client import get_llm

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Shared singleton (retriever is stateless, LLM client is lazily built) ──
_retriever = KnowledgeBaseRetriever()


def _get_generator() -> ContentGenerator:
    return ContentGenerator(llm_client=get_llm(), retriever=_retriever)


# ── Pydantic schemas ────────────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    template: GenerationTemplate
    user_prompt: str = Field(..., min_length=1, max_length=10000)
    context_query: str = ""     # 用於 RAG 檢索的查詢詞（可與 prompt 不同）
    max_tokens: int = Field(default=3000, ge=100, le=16000)
    document_ids: List[str] = []  # P11-3: 指定文件 ID 直接帶入上下文（跨案件生成）

    @field_validator("user_prompt")
    @classmethod
    def prompt_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("提示詞不能為空白")
        return v.strip()


class ExportRequest(BaseModel):
    content: str
    title: str = "生成文件"
    sources: List[dict] = []
    template: Optional[GenerationTemplate] = None


# ── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/templates")
async def list_templates(current_user=Depends(get_current_active_user)):
    """列出所有可用的生成模板。"""
    meta = {
        "draft_response": {
            "name": "函件草稿",
            "desc": "公文格式：主旨→說明→辦法→結語",
            "output": "正式函件 Markdown（含受文者、說明、辦法、結語、附件）",
        },
        "case_summary": {
            "name": "案件摘要",
            "desc": "背景·當事人·時間線·待辦 結構化整理",
            "output": "案件摘要（含資訊表格、時間線、待辦清單）",
        },
        "meeting_minutes": {
            "name": "會議記錄",
            "desc": "議題→決議→行動追蹤表 含負責人/期限",
            "output": "會議紀錄（含出席、議題、決議、行動追蹤表格）",
        },
        "analysis_report": {
            "name": "分析報告",
            "desc": "跨文件趨勢·風險機會矩陣·策略建議",
            "output": "深度分析報告（含摘要、發現、趨勢、風險矩陣、建議）",
        },
        "faq_draft": {
            "name": "FAQ 問答集",
            "desc": "Q&A 對照格式 自動提取 5-10 個常見問題",
            "output": "FAQ 列表（含問題、答案、來源標注）",
        },
    }
    return {
        "templates": [
            {
                "id": t.value,
                "name": meta.get(t.value, {}).get("name", t.value),
                "desc": meta.get(t.value, {}).get("desc", ""),
                "output": meta.get(t.value, {}).get("output", ""),
            }
            for t in GenerationTemplate
        ]
    }


@router.post("/stream")
async def generate_stream(
    req: GenerateRequest,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    RAG 增強內容生成，SSE 串流回傳。
    前端使用 fetch + ReadableStream 接收（POST SSE）。

    P11-3: document_ids 可指定多筆文件直接帶入上下文（跨案件生成）。

    事件格式：
      data: {"content": "<chunk>"}\n\n
      data: [DONE]\n\n
    """
    tenant_id = str(current_user.tenant_id)
    generator = _get_generator()

    # P11-3: Fetch content of explicitly specified documents from DB
    extra_context = ""
    if req.document_ids:
        from app.models.document import Document, DocumentChunk
        from uuid import UUID
        parts = []
        for doc_id in req.document_ids[:10]:  # cap at 10 docs
            try:
                doc = db.query(Document).filter(
                    Document.id == UUID(doc_id),
                    Document.tenant_id == current_user.tenant_id,
                ).first()
                if doc:
                    # Fetch chunk text as document content
                    chunks = (
                        db.query(DocumentChunk.text)
                        .filter(DocumentChunk.document_id == doc.id)
                        .order_by(DocumentChunk.chunk_index)
                        .limit(20)
                        .all()
                    )
                    content_preview = "\n".join(c.text for c in chunks)[:2000]
                    parts.append(f"【{doc.filename or doc_id}】\n{content_preview}")
            except Exception:
                pass
        extra_context = "\n\n".join(parts)

    async def event_stream():
        total_output = 0
        all_chunks: list[str] = []
        had_error = False
        try:
            async for chunk in generator.generate_stream(
                template=req.template,
                user_prompt=req.user_prompt,
                context_query=req.context_query,
                tenant_id=tenant_id,
                max_tokens=req.max_tokens,
                extra_context=extra_context,
            ):
                total_output += len(chunk)
                all_chunks.append(chunk)
                yield f"data: {json.dumps({'content': chunk}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            logger.exception("generate_stream error: %s", exc)
            had_error = True
            yield f"data: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"
        finally:
            # Phase 11-2: auto-save report to DB
            report_id = None
            if all_chunks and not had_error:
                try:
                    from app.crud import crud_report
                    full_content = "".join(all_chunks)
                    # Auto-generate title from first line of content
                    first_line = full_content.strip().split("\n")[0].strip("# ").strip()[:80]
                    auto_title = first_line if first_line else "未命名報告"

                    template_labels = {
                        "draft_response": "函件草稿",
                        "case_summary": "案件摘要",
                        "meeting_minutes": "會議記錄",
                        "analysis_report": "分析報告",
                        "faq_draft": "FAQ 問答集",
                    }
                    tpl_val = req.template.value if hasattr(req.template, 'value') else str(req.template)
                    label = template_labels.get(tpl_val, tpl_val)
                    if not first_line:
                        auto_title = f"{label} - {req.user_prompt[:40]}"

                    report = crud_report.create_report(
                        db,
                        tenant_id=current_user.tenant_id,
                        created_by=current_user.id,
                        title=auto_title,
                        template=tpl_val,
                        prompt=req.user_prompt,
                        context_query=req.context_query or None,
                        content=full_content,
                        document_ids=req.document_ids or [],
                    )
                    report_id = str(report.id)
                    yield f"data: {json.dumps({'report_id': report_id}, ensure_ascii=False)}\n\n"
                except Exception:
                    logger.warning("Failed to auto-save generated report to DB")

            yield "data: [DONE]\n\n"
            # Log usage after stream completes
            try:
                from app.api.v1.endpoints.audit import log_usage
                input_tokens = (len(req.user_prompt) + len(req.context_query) + len(extra_context)) // 2
                output_tokens = total_output // 2
                log_usage(
                    db,
                    tenant_id=current_user.tenant_id,
                    user_id=current_user.id,
                    action_type="content_generate",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    metadata={"template": req.template.value, "report_id": report_id},
                )
            except Exception:
                logger.warning("Failed to log usage for content generation")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/export/docx")
async def export_docx(
    req: ExportRequest,
    current_user=Depends(get_current_active_user),
):
    """將生成內容匯出為 Word 檔案（.docx）。"""
    generator = _get_generator()
    try:
        docx_bytes = await generator.export_to_docx(
            content=req.content,
            title=req.title,
            sources=req.sources,
        )
    except ImportError:
        raise HTTPException(status_code=501, detail="python-docx 套件未安裝，無法匯出 Word")
    except Exception as exc:
        logger.exception("DOCX export failed")
        raise HTTPException(status_code=500, detail=f"DOCX 匯出失敗：{exc}")
    safe_title = req.title.replace(" ", "_")[:50]
    encoded_title = quote(safe_title)
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename=\"{encoded_title}.docx\"; filename*=UTF-8''{encoded_title}.docx"
        },
    )


@router.post("/export/pdf")
async def export_pdf(
    req: ExportRequest,
    current_user=Depends(get_current_active_user),
):
    """將生成內容匯出為 PDF。"""
    generator = _get_generator()
    try:
        pdf_bytes = await generator.export_to_pdf(
            content=req.content,
            title=req.title,
            sources=req.sources,
        )
    except ImportError:
        raise HTTPException(status_code=501, detail="reportlab 套件未安裝，無法匯出 PDF")
    except Exception as exc:
        logger.exception("PDF export failed")
        raise HTTPException(status_code=500, detail=f"PDF 匯出失敗：{exc}")
    safe_title = req.title.replace(" ", "_")[:50]
    encoded_title = quote(safe_title)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=\"{encoded_title}.pdf\"; filename*=UTF-8''{encoded_title}.pdf"
        },
    )
