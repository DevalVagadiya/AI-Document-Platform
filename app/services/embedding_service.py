from sentence_transformers import SentenceTransformer

from app.core.config import settings


class EmbeddingService:
    """
    Singleton service for generating embeddings locally using SentenceTransformers.
    """

    def __init__(self):
        # This will download the model weights (usually ~80MB for all-MiniLM-L6-v2)
        # on the first run and cache them in ~/.cache/huggingface/
        self.model = SentenceTransformer(settings.EMBEDDING_MODEL)

    def embed_text(self, text: str) -> list[float]:
        """Synchronously embed a single text string."""
        # encode() returns a numpy array, we convert to list of floats
        embedding = self.model.encode(text)
        return embedding.tolist()

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Synchronously embed a list of strings."""
        if not texts:
            return []
        embeddings = self.model.encode(texts)
        return embeddings.tolist()


# Singleton instance loaded on import
embedding_service = EmbeddingService()
