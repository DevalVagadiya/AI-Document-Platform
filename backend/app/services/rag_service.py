import asyncio
import json
import logging
import uuid
from typing import AsyncGenerator

from google import genai
from google.genai import types
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.document import Document
from app.models.query_log import QueryLog
from app.models.user import User
from app.schemas.query import ChunkMatch
from app.services.embedding_service import embedding_service
from app.services.vector_service import vector_service

logger = logging.getLogger(__name__)


class RagService:
    def __init__(self, db: AsyncSession):
        self._db = db
        # Initialize Google GenAI client only if needed
        self.ai_client = None
        if settings.LLM_PROVIDER == "gemini":
            self.ai_client = genai.Client(api_key=settings.GEMINI_API_KEY)

    async def get_history(self, tenant_id: uuid.UUID, user_id: uuid.UUID, limit: int = 3) -> list[QueryLog]:
        """Fetches recent conversation history for context injection."""
        result = await self._db.execute(
            select(QueryLog)
            .where(QueryLog.tenant_id == tenant_id, QueryLog.user_id == user_id)
            .order_by(QueryLog.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())[::-1]  # Reverse to chronological order

    def _build_prompt(self, question: str, chunks: list[ChunkMatch], history: list[QueryLog]) -> str:
        """Constructs the LLM prompt with context and history."""
        context_blocks = []
        for i, chunk in enumerate(chunks, 1):
            context_blocks.append(f"[Source {i}]\n{chunk.content}")
        
        context_str = "\n\n".join(context_blocks)
        
        history_str = ""
        if history:
            history_blocks = []
            for log in history:
                if log.question and log.answer:
                    history_blocks.append(f"User: {log.question}\nAssistant: {log.answer}")
            if history_blocks:
                history_str = "\n---\nRecent Conversation History:\n" + "\n\n".join(history_blocks)

        return (
            f"You are a helpful AI assistant for document intelligence.\n"
            f"Provide a complete, direct, and well-structured answer to the user's question based strictly on the provided context.\n"
            f"If the answer cannot be determined from the context, state clearly that you do not know.\n\n"
            f"Document Context:\n{context_str}\n"
            f"{history_str}\n\n"
            f"User Question: {question}\n"
            f"Detailed Answer:"
        )

    async def generate_answer_stream(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        question: str,
        document_id: uuid.UUID,
        strict_search: bool = False,
    ) -> AsyncGenerator[str, None]:
        """
        Executes the RAG pipeline and yields SSE-formatted chunks.
        """
        import time
        start_time = time.time()
        
        try:
            # Check user roles to determine document access scope
            user_res = await self._db.execute(select(User).where(User.id == user_id))
            user_obj = user_res.scalar_one_or_none()
            is_admin = bool(user_obj and "admin" in user_obj.roles)

            allowed_doc_ids: list[str] | None = None
            if not is_admin:
                if document_id:
                    # Verify user owns the specific requested document
                    doc_res = await self._db.execute(
                        select(Document).where(Document.id == document_id, Document.uploaded_by_id == user_id)
                    )
                    if not doc_res.scalar_one_or_none():
                        allowed_doc_ids = []  # User does not own this document
                else:
                    # Get list of all documents uploaded by this user
                    docs_res = await self._db.execute(
                        select(Document.id).where(Document.tenant_id == tenant_id, Document.uploaded_by_id == user_id)
                    )
                    allowed_doc_ids = [str(d) for d in docs_res.scalars().all()]

            # 1. Embed the query
            import anyio
            query_embedding = await anyio.to_thread.run_sync(
                embedding_service.embed_text, question
            )

            # Determine similarity threshold: strict=0.35, normal=0.20
            threshold = 0.35 if strict_search else 0.20

            # 2. Retrieve context from ChromaDB
            chunks = await anyio.to_thread.run_sync(
                vector_service.search,
                tenant_id,
                query_embedding,
                settings.MAX_CHUNKS_PER_QUERY,
                document_id,
                threshold,
                allowed_doc_ids,
            )

            # Yield sources as the first SSE message
            sources_json = json.dumps([c.model_dump(mode="json") for c in chunks])
            yield {"event": "sources", "data": sources_json}

            if not chunks:
                yield {"event": "message", "data": "I could not find any relevant documents to answer your question."}
                return

            # 3. Get history and build prompt
            history = await self.get_history(tenant_id, user_id)
            prompt = self._build_prompt(question, chunks, history)

            # 4. Stream from the configured LLM Provider
            import asyncio
            
            if settings.LLM_PROVIDER == "ollama":
                import httpx
                
                payload = {
                    "model": settings.OLLAMA_MODEL,
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    "options": {
                        "temperature": settings.GEMINI_TEMPERATURE,
                        "num_predict": settings.GEMINI_MAX_OUTPUT_TOKENS,
                    },
                    "stream": True
                }
                
                full_response = []
                url = f"{settings.OLLAMA_URL.rstrip('/')}/api/chat"
                
                try:
                    # 5-minute read timeout for model generation / first token time on CPU
                    timeout_config = httpx.Timeout(300.0, connect=10.0)
                    async with httpx.AsyncClient(timeout=timeout_config) as client:
                        async with client.stream("POST", url, json=payload) as response:
                            if response.status_code != 200:
                                error_text = await response.aread()
                                raise RuntimeError(f"Ollama returned status code {response.status_code}: {error_text.decode()}")
                            
                            async for line in response.aiter_lines():
                                if not line:
                                    continue
                                data = json.loads(line)
                                delta_text = data.get("message", {}).get("content", "")
                                if delta_text:
                                    full_response.append(delta_text)
                                    text_delta = json.dumps(delta_text)
                                    yield {"event": "delta", "data": text_delta}
                                if data.get("done", False):
                                    break
                except httpx.ReadTimeout:
                    logger.exception("Ollama API read timeout")
                    raise RuntimeError("Ollama request timed out (model took >300s to respond). Please try again or check if Ollama is responsive.")
                except Exception as e:
                    logger.exception("Ollama API connection failed")
                    err_msg = str(e) if str(e) else type(e).__name__
                    raise RuntimeError(f"Ollama connection error: {err_msg}")
            else:
                from google.genai.errors import APIError
                
                # Check for dummy/mock API key to run locally without a real Google API key
                is_mock_key = (
                    not settings.GEMINI_API_KEY
                    or settings.GEMINI_API_KEY in ("your-google-ai-api-key-here", "test-gemini-key", "mock")
                    or "mock" in settings.GEMINI_API_KEY.lower()
                    or "test" in settings.GEMINI_API_KEY.lower()
                )

                if is_mock_key:
                    mock_text = (
                        f"[Mock Mode] No valid GEMINI_API_KEY was detected. "
                        f"Here is a mock response using your retrieved document context:\n\n"
                    )
                    for i, chunk in enumerate(chunks, 1):
                        mock_text += f"- **Source {i}**: {chunk.content}\n"
                    
                    full_response = [mock_text]
                    for word in mock_text.split(" "):
                        await asyncio.sleep(0.02)
                        yield {"event": "delta", "data": json.dumps(word + " ")}
                else:
                    full_response = []
                    max_retries = 3
                    retry_delay = 1.0
                    
                    for attempt in range(max_retries):
                        try:
                            # Safely access ai_client since we are in gemini mode
                            if not self.ai_client:
                                raise RuntimeError("GenAI client is not initialized.")
                                
                            response_stream = await self.ai_client.aio.models.generate_content_stream(
                                model=settings.GEMINI_MODEL,
                                contents=prompt,
                                config=types.GenerateContentConfig(
                                    temperature=settings.GEMINI_TEMPERATURE,
                                    max_output_tokens=settings.GEMINI_MAX_OUTPUT_TOKENS,
                                )
                            )

                            async for chunk in response_stream:
                                if chunk.text:
                                    full_response.append(chunk.text)
                                    text_delta = json.dumps(chunk.text)
                                    yield {"event": "delta", "data": text_delta}
                            
                            break # Success, break out of retry loop
                        except Exception as e:
                            logger.warning(f"Gemini API error on attempt {attempt + 1}/{max_retries}: {e}")
                            if attempt == max_retries - 1:
                                raise
                            await asyncio.sleep(retry_delay * (2 ** attempt)) # Exponential backoff

            # 5. Log the query
            latency_ms = int((time.time() - start_time) * 1000)
            answer_text = "".join(full_response)
            
            # Simple token approximation for logging (tiktoken for prompt, word count for response)
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            prompt_tokens = len(enc.encode(prompt))
            completion_tokens = len(enc.encode(answer_text))

            query_log = QueryLog(
                tenant_id=tenant_id,
                user_id=user_id,
                document_id=document_id,
                question=question,
                answer=answer_text,
                chunks_retrieved=len(chunks),
                latency_ms=latency_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                similarity_score=chunks[0].similarity_score if chunks else None
            )
            self._db.add(query_log)
            await self._db.commit()

            yield {"event": "done", "data": "{}"}

        except Exception as e:
            logger.exception("RAG Pipeline failed")
            yield {"event": "error", "data": json.dumps(str(e))}
            
            # Log the error
            query_log = QueryLog(
                tenant_id=tenant_id,
                user_id=user_id,
                document_id=document_id,
                question=question,
                error=str(e),
                latency_ms=int((time.time() - start_time) * 1000)
            )
            self._db.add(query_log)
            await self._db.commit()
