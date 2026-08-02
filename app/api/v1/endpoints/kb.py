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
    
    try:
        from app.core.authorization import AuthorizationContext
        from app.services.retrieval_facade import get_retrieval_facade
        authz = AuthorizationContext.from_user(current_user)
        facade = get_retrieval_facade()
        retrieved = facade.search(
            authz=authz,
            query=request.query,
            top_k=request.top_k,
        )
        results = retrieved.results
        
        search_results = [
            SearchResult(
                score=r["score"],
                content=r.get("content") or r.get("text") or "",
                filename=r.get("filename") or "",
                document_id=r["document_id"],
                chunk_index=r.get("chunk_index") or 0,
            )
            for r in results
        ]
        
        return SearchResponse(
            query=request.query,
            results=search_results,
            total_results=len(search_results)
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
