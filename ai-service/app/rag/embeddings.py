import os

from google import genai
from google.genai import types

EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "768"))
BATCH_SIZE = 20

_client = None


def enabled() -> bool:
    """Chỉ bật embedding khi đang dùng Gemini và có API key."""
    provider = os.getenv("LLM_PROVIDER", "mock").strip().lower()
    return provider == "gemini" and bool(os.getenv("GEMINI_API_KEY", "").strip())


def _get_client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.getenv("GEMINI_API_KEY", "").strip())
    return _client


def embed_texts(texts, task_type):
    """Đồng bộ (gọi trong thread). task_type: RETRIEVAL_DOCUMENT hoặc RETRIEVAL_QUERY."""
    client = _get_client()
    vectors = []

    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i:i + BATCH_SIZE]
        resp = client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=batch,
            config=types.EmbedContentConfig(
                task_type=task_type,
                output_dimensionality=EMBEDDING_DIM,
            ),
        )
        if len(resp.embeddings) != len(batch):
            raise RuntimeError("Embedding API returned an unexpected number of vectors")
        vectors.extend(e.values for e in resp.embeddings)

    return vectors


def to_pgvector(values) -> str:
    """Chuyển list số thành literal của pgvector: '[0.1,0.2,...]'."""
    return "[" + ",".join(f"{x:.6f}" for x in values) + "]"