from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api import deps
from app.models.user import User
from app.services.kb_retrieval import KnowledgeBaseRetriever

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
    results: list[SearchResult]
    total_results: int
    granularity: str = "chunk"  # 實際使用的檢索臂（回顯，防靜默降級）


@router.post("/search", response_model=SearchResponse)
def search_knowledge_base(
    *,
    request: SearchRequest,
    db: Annotated[Session, Depends(deps.get_db)],
    current_user: Annotated[User, Depends(deps.get_current_active_user)],
) -> Any:
    """
    在租戶知識庫中搜尋相關內容
    """
    if not request.query.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="查詢內容不能為空",
        )
    if request.granularity not in ("catalog", "chunk", "auto"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="granularity 必須是 catalog | chunk | auto",
        )

    from app.core.authorization import AuthorizationContext
    from app.services.kb_scope_policy import resolve_kb_revision_scope
    from app.services.query_plan import build_query_plan
    from app.services.retrieval_facade import get_retrieval_facade

    authz = AuthorizationContext.from_user(current_user)
    facade = get_retrieval_facade()
    plan = build_query_plan(request.query)
    scope = resolve_kb_revision_scope(authz=authz, requested=None, db=db)

    granularity = request.granularity
    if granularity == "auto":
        # ``compare`` plans also carry a catalog arm for multi-document fusion,
        # but a single-arm public search must still retrieve passage evidence.
        # Reserve catalog-only routing for actual inventory/listing intents.
        granularity = (
            "catalog" if plan.intent in {"inventory", "multi_hop"} else "chunk"
        )

    if granularity == "catalog":
        catalog_queries = plan.sub_queries or [request.query]
        seen: set[str] = set()
        merged_hits = []
        for catalog_query in catalog_queries:
            for hit in facade.search_catalog(
                authz=authz,
                query=catalog_query,
                top_k=max(request.top_k, 50),
                filters=scope,
                db=db,
            ):
                hit_id = hit.document_id or hit.filename
                if hit_id in seen:
                    continue
                seen.add(hit_id)
                merged_hits.append(hit)
        search_results = [
            SearchResult(
                score=hit.score,
                content=hit.content_or_summary,
                filename=hit.filename or "",
                document_id=hit.document_id or "",
                chunk_index=0,
            )
            for hit in merged_hits
        ]
    else:
        retrieved = facade.search(
            authz=authz,
            query=request.query,
            top_k=request.top_k,
            db=db,
            scope=scope,
        )
        search_results = [
            SearchResult(
                score=result["score"],
                content=result.get("content") or result.get("text") or "",
                filename=result.get("filename") or "",
                document_id=result["document_id"],
                chunk_index=result.get("chunk_index") or 0,
            )
            for result in retrieved.results
        ]

    return SearchResponse(
        query=request.query,
        results=search_results,
        total_results=len(search_results),
        granularity=granularity,
    )


@router.get("/stats")
def get_kb_stats(
    current_user: Annotated[User, Depends(deps.get_current_active_user)],
) -> Any:
    """
    獲取當前租戶知識庫統計資訊
    """
    retriever = KnowledgeBaseRetriever()
    return retriever.get_stats(current_user.tenant_id)
