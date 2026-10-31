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
from app.models.query_log import QueryLog
from app.schemas.query import ChunkMatch
from app.services.embedding_service import embedding_service
from app.services.vector_service import vector_service

logger = logging.getLogger(__name__)


class RagService:
    def __init__(self, db: AsyncSession):
        self._db = db
        # Initialize Google GenAI client
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
                history_blocks.append(f"User: {log.question}\nAssistant: {log.answer}")
            history_str = "\n\n".join(history_blocks)
            history_str = f"## Conversation History\n{history_str}\n\n"

        prompt = f"""You are a helpful and highly accurate AI Document Assistant.
Answer the user's question based ONLY on the provided document context.
If the answer cannot be found in the context, politely state that you do not know.
Do not hallucinate or make up information outside of the context.
When applicable, reference the source numbers (e.g., [Source 1]).

{history_str}## Context
{context_str}

## Question
{question}
"""
        return prompt

    async def generate_answer_stream(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID, question: str, document_id: uuid.UUID | None = None
    ) -> AsyncGenerator[str, None]:
        """
        Executes the RAG pipeline and yields SSE-formatted chunks.
        """
        import time
        start_time = time.time()
        
        try:
            # 1. Embed the query
            import anyio
            query_embedding = await anyio.to_thread.run_sync(
                embedding_service.embed_text, question
            )

            # 2. Retrieve context from ChromaDB
            chunks = await anyio.to_thread.run_sync(
                vector_service.search,
                tenant_id,
                query_embedding,
                settings.MAX_CHUNKS_PER_QUERY,
                document_id
            )

            # Yield sources as the first SSE message
            sources_json = json.dumps([c.model_dump(mode="json") for c in chunks])
            yield f"event: sources\ndata: {sources_json}\n\n"

            if not chunks:
                yield "event: message\ndata: I could not find any relevant documents to answer your question.\n\n"
                return

            # 3. Get history and build prompt
            history = await self.get_history(tenant_id, user_id)
            prompt = self._build_prompt(question, chunks, history)

            # 4. Stream from Gemini with Retries
            import asyncio
            from google.genai.errors import APIError
            
            full_response = []
            max_retries = 3
            retry_delay = 1.0
            
            for attempt in range(max_retries):
                try:
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
                            yield f"event: delta\ndata: {text_delta}\n\n"
                    
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

            yield "event: done\ndata: {}\n\n"

        except Exception as e:
            logger.exception("RAG Pipeline failed")
            yield f"event: error\ndata: {json.dumps(str(e))}\n\n"
            
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
