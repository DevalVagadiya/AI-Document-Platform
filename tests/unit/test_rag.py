import uuid
import pytest
from app.services.rag_service import RagService
from app.schemas.query import ChunkMatch
from app.models.query_log import QueryLog


@pytest.mark.asyncio
async def test_build_prompt():
    service = RagService(db=None) # type: ignore
    
    question = "What is the policy?"
    
    chunks = [
        ChunkMatch(
            chunk_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            content="The policy is strict.",
            similarity_score=0.9
        )
    ]
    
    history = [
        QueryLog(question="Hello", answer="Hi there")
    ]
    
    prompt = service._build_prompt(question, chunks, history)
    
    assert "User: Hello" in prompt
    assert "Assistant: Hi there" in prompt
    assert "[Source 1]" in prompt
    assert "The policy is strict." in prompt
    assert "What is the policy?" in prompt
