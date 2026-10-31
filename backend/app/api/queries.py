from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.core.dependencies import AuthUser, get_db
from app.schemas.query import QueryLogResponse, QueryRequest
from app.services.rag_service import RagService

router = APIRouter(prefix="/queries", tags=["queries"])


@router.post(
    "",
    summary="Ask a question (RAG streaming)",
)
async def ask_question(
    request: QueryRequest,
    current_user: AuthUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Submit a question to the AI assistant. 
    The response is an SSE stream yielding source citations and LLM tokens.
    """
    if not request.document_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="document_id is required. Please select a document to query."
        )

    service = RagService(db)
    
    stream = service.generate_answer_stream(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        question=request.question,
        document_id=request.document_id,
        strict_search=request.strict_search,
    )
    
    return EventSourceResponse(stream)


@router.get(
    "",
    response_model=list[QueryLogResponse],
    summary="Get conversation history",
)
async def get_history(
    current_user: AuthUser,
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
):
    """
    Retrieve the recent queries made by the current user.
    """
    service = RagService(db)
    history = await service.get_history(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        limit=limit
    )
    return history
