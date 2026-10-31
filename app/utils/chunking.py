import tiktoken


def chunk_text(text: str, chunk_size: int = 512, chunk_overlap: int = 64) -> list[str]:
    """
    Splits text into chunks of maximum `chunk_size` tokens using `tiktoken`.
    Includes a sliding window of `chunk_overlap` tokens to preserve semantic context.
    """
    if not text.strip():
        return []

    # Using cl100k_base which is standard for modern models (OpenAI, and roughly matches many sentence-transformers)
    enc = tiktoken.get_encoding("cl100k_base")
    tokens = enc.encode(text)

    chunks = []
    start = 0
    while start < len(tokens):
        # The end of the current chunk
        end = start + chunk_size
        chunk_tokens = tokens[start:end]
        
        # Decode tokens back to text
        chunk_text = enc.decode(chunk_tokens)
        chunks.append(chunk_text.strip())
        
        # Move start forward, but step back by chunk_overlap
        # If the remaining tokens are less than chunk_overlap, we're done
        if end >= len(tokens):
            break
        
        start = end - chunk_overlap

    return chunks
