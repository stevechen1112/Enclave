from typing import Any, List, Dict
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api import deps
from app.models.user import User
from app.services.kb_retrieval import KnowledgeBaseRetriever
from app.config import settings

router = APIRouter()


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5
    # ADR-008：catalog（文件層）| chunk（段落層，預設保相容）| auto（依查詢意圖選臂）
    granularity: str = "chunk"


class SearchResult(BaseModel):
    score: float
    content: str
    filename: str
    document_id: str
    chunk_index: int


class SearchResponse(BaseModel):
    query: str
    results: List[SearchResult]
    total_results: int
    granularity: str = "chunk"  # 實際使用的檢索臂（回顯，防靜默降級）


@router.post("/search", response_model=SearchResponse)
def search_knowledge_base(
    *,
    request: SearchRequest,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    在租戶知識庫中搜尋相關內容
    """
    if not request.query.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="查詢內容不能為空"
        )
    if request.granularity not in ("catalog", "chunk", "auto"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="granularity 必須是 catalog | chunk | auto"
        )

    try:
        from app.core.authorization import AuthorizationContext
        from app.services.query_plan import build_query_plan
        from app.services.retrieval_facade import get_retrieval_facade
        authz = AuthorizationContext.from_user(current_user)
        facade = get_retrieval_facade()
        plan = build_query_plan(request.query)

        granularity = request.granularity
        if granularity == "auto":
            granularity = "catalog" if plan.wants_catalog else "chunk"

        if granularity == "catalog":
            catalog_queries = plan.sub_queries or [request.query]
            seen: set = set()
            merged_hits = []
            for cq in catalog_queries:
                for h in facade.search_catalog(
                    authz=authz,
                    query=cq,
                    top_k=max(request.top_k, 50),
                ):
                    hid = h.document_id or h.filename
                    if hid in seen:
                        continue
                    seen.add(hid)
                    merged_hits.append(h)
            hits = merged_hits
            search_results = [
                SearchResult(
                    score=h.score,
                    content=h.content_or_summary,
                    filename=h.filename or "",
                    document_id=h.document_id or "",
                    chunk_index=0,
                )
                for h in hits
            ]
        else:
            retrieved = facade.search(
                authz=authz,
                query=request.query,
                top_k=request.top_k,
            )
            search_results = [
                SearchResult(
                    score=r["score"],
                    content=r.get("content") or r.get("text") or "",
                    filename=r.get("filename") or "",
                    document_id=r["document_id"],
                    chunk_index=r.get("chunk_index") or 0,
                )
                for r in retrieved.results
            ]

        return SearchResponse(
            query=request.query,
            results=search_results,
            total_results=len(search_results),
            granularity=granularity,
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"檢索失敗: {str(e)}"
        )


@router.get("/stats")
def get_kb_stats(
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    獲取當前租戶知識庫統計資訊
    """
    try:
        retriever = KnowledgeBaseRetriever()
        stats = retriever.get_stats(current_user.tenant_id)
        return stats
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"獲取統計資訊失敗: {str(e)}"
        )
