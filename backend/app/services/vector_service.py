import logging
import uuid
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.core.config import settings
from app.models.chunk import DocumentChunk
from app.schemas.query import ChunkMatch

logger = logging.getLogger(__name__)


class VectorService:
    """
    Service for interacting with ChromaDB.
    Uses a single global collection and filters strictly by tenant_id.
    """

    def __init__(self):
        # Fallback to local PersistentClient if HTTP client fails or in local mode
        try:
            # If CHROMA_PORT matches Uvicorn port (8000), use PersistentClient directly
            if settings.CHROMA_PORT != 8000 and (settings.is_production or settings.CHROMA_HOST):
                self.client = chromadb.HttpClient(
                    host=settings.CHROMA_HOST,
                    port=settings.CHROMA_PORT,
                    settings=ChromaSettings(anonymized_telemetry=False)
                )
                self.client.heartbeat()  # Test connection
            else:
                self.client = chromadb.PersistentClient(path="./chroma_db")
        except Exception as e:
            logger.warning(f"Could not connect to ChromaDB at {settings.CHROMA_HOST}:{settings.CHROMA_PORT}. Using PersistentClient: {e}")
            self.client = chromadb.PersistentClient(path="./chroma_db")

        # We use a single collection and rely on metadata filtering
        self.collection_name = "document_chunks"
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"} # Cosine similarity is usually best for sentence-transformers
        )

    def add_chunks(self, tenant_id: uuid.UUID, document_id: uuid.UUID, chunks: list[DocumentChunk], embeddings: list[list[float]]):
        """
        Stores chunks and their embeddings into ChromaDB.
        """
        if not chunks:
            return

        ids = [chunk.chroma_id for chunk in chunks]
        documents = [chunk.content for chunk in chunks]
        
        # Metadata must be strings, ints, or floats
        metadatas = [
            {
                "tenant_id": str(tenant_id),
                "document_id": str(document_id),
                "chunk_index": chunk.chunk_index,
                "chunk_id": str(chunk.id),
                "token_count": chunk.token_count,
            }
            for chunk in chunks
        ]

        self.collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas
        )

    def search(
        self, 
        tenant_id: uuid.UUID, 
        query_embedding: list[float], 
        top_k: int = 5,
        document_id: uuid.UUID | None = None,
        similarity_threshold: float | None = None,
        allowed_document_ids: list[str] | None = None,
    ) -> list[ChunkMatch]:
        """
        Searches for the most relevant chunks. Strictly isolated by tenant_id and optional document scoping.
        """
        threshold = similarity_threshold if similarity_threshold is not None else settings.SIMILARITY_THRESHOLD
        where_filter: dict[str, Any] = {"tenant_id": str(tenant_id)}
        
        if allowed_document_ids is not None and len(allowed_document_ids) == 0:
            return []

        if document_id:
            if allowed_document_ids is not None and str(document_id) not in allowed_document_ids:
                return []
            where_filter = {
                "$and": [
                    {"tenant_id": str(tenant_id)},
                    {"document_id": str(document_id)}
                ]
            }
        elif allowed_document_ids is not None:
            if len(allowed_document_ids) == 1:
                where_filter = {
                    "$and": [
                        {"tenant_id": str(tenant_id)},
                        {"document_id": allowed_document_ids[0]}
                    ]
                }
            else:
                where_filter = {
                    "$and": [
                        {"tenant_id": str(tenant_id)},
                        {"document_id": {"$in": allowed_document_ids}}
                    ]
                }

        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where_filter,
            include=["documents", "metadatas", "distances"]
        )

        matches = []
        if not results["ids"] or not results["ids"][0]:
            return matches

        all_candidate_matches = []
        for idx, (doc_id, distance, metadata, content) in enumerate(zip(
            results["ids"][0],
            results["distances"][0],  # type: ignore
            results["metadatas"][0],  # type: ignore
            results["documents"][0]   # type: ignore
        )):
            # Convert cosine distance to similarity score
            similarity = 1.0 - distance
            item = ChunkMatch(
                chunk_id=uuid.UUID(metadata["chunk_id"]),
                document_id=uuid.UUID(metadata["document_id"]),
                content=content,
                similarity_score=round(float(similarity), 4),
            )
            all_candidate_matches.append(item)
            
            # Apply similarity threshold
            if similarity >= threshold:
                matches.append(item)

        # Fallback to top candidates if no chunks passed threshold when searching a specific document
        if not matches and document_id and all_candidate_matches:
            matches = all_candidate_matches[:3]

        return matches

    def delete_document_chunks(self, tenant_id: uuid.UUID, document_id: uuid.UUID):
        """
        Deletes all chunks for a given document from ChromaDB.
        """
        self.collection.delete(
            where={
                "$and": [
                    {"tenant_id": str(tenant_id)},
                    {"document_id": str(document_id)}
                ]
            }
        )

# Singleton
vector_service = VectorService()
