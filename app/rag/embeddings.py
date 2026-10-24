"""Embeddings through Ollama.

Turns each piece of text into a list of 768 numbers (embeddinggemma), so
pieces with similar meaning are close together and can be found by search.
The search itself runs in Postgres with pgvector, not in memory.
"""

from __future__ import annotations

import numpy as np

from config import OLLAMA_BASE_URL, OLLAMA_EMBED_MODEL


class OllamaEmbedder:
    def __init__(self, model: str | None = None, base_url: str | None = None):
        self.model = model or OLLAMA_EMBED_MODEL
        self.base_url = (base_url or OLLAMA_BASE_URL).rstrip("/")

    def encode(self, texts: list[str]) -> np.ndarray:
        import requests
        response = requests.post(
            f"{self.base_url}/api/embed",
            json={"model": self.model, "input": texts},
            timeout=180,
        )
        response.raise_for_status()
        return np.asarray(response.json()["embeddings"], dtype=np.float32)
