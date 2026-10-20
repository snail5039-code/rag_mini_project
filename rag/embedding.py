"""Gemini 임베딩. 모델과 차원은 config(.env)에서 하나로 고정한다."""
from __future__ import annotations

import os
import time

from dotenv import load_dotenv

from . import config

load_dotenv(config.ROOT / ".env")


def embed_text(section_title: str | None, content: str) -> str:
    """child 본문 앞에 제목을 붙여 임베딩 입력으로 쓴다."""
    return f"제목: {section_title}\n\n{content}" if section_title else content


class GeminiEmbedder:
    def __init__(self, model: str = config.EMBEDDING_MODEL, dim: int = config.EMBEDDING_DIM,
                 batch_size: int = 32, use_task_type: bool | None = None):
        from google import genai
        from google.genai import types

        self._types = types
        self.model, self.dim, self.batch_size = model, dim, batch_size
        # task_type 지원 여부는 모델마다 다르므로 기본은 끄고 EMBEDDING_USE_TASK_TYPE=1로 켠다.
        self.use_task_type = (os.getenv("EMBEDDING_USE_TASK_TYPE") == "1") if use_task_type is None else use_task_type
        self.client = genai.Client(
            api_key=os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"),
            http_options=types.HttpOptions(
                retry_options=types.HttpRetryOptions(attempts=8, initial_delay=2.0, max_delay=60.0, exp_base=2, jitter=1.0)
            ),
        )

    def _embed(self, texts: list[str], task_type: str) -> list[list[float]]:
        cfg = {"output_dimensionality": self.dim}
        if self.use_task_type:
            cfg["task_type"] = task_type
        # gemini-embedding-2는 문자열 목록을 하나의 콘텐츠로 보고 임베딩 1개로 합친다.
        # 텍스트마다 Content로 감싸서 보내야 텍스트 수만큼 임베딩이 돌아온다.
        contents = [self._types.Content(parts=[self._types.Part(text=t)]) for t in texts]
        res = self.client.models.embed_content(
            model=self.model, contents=contents, config=self._types.EmbedContentConfig(**cfg)
        )
        vectors = [list(e.values) for e in res.embeddings]
        if len(vectors) != len(texts):
            raise ValueError(f"임베딩 수({len(vectors)})가 입력 수({len(texts)})와 다릅니다.")
        if any(len(v) != self.dim for v in vectors):
            raise ValueError(f"임베딩 차원이 {self.dim}이 아닙니다: {len(vectors[0])}")
        return vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            out += self._embed(texts[i:i + self.batch_size], "RETRIEVAL_DOCUMENT")
            time.sleep(0.2)
        return out

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], "RETRIEVAL_QUERY")[0]


class CachedQueryEmbedder:
    """평가에서 같은 질문을 반복 임베딩하지 않도록 질문 벡터를 파일에 저장해 둔다."""

    def __init__(self, embedder: GeminiEmbedder | None = None, path=config.ROOT / ".cache" / "query_embeddings.json"):
        import json

        self._json = json
        self.embedder = embedder or GeminiEmbedder()
        self.path = path
        self.cache = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def _key(self, text: str) -> str:
        import hashlib
        return hashlib.sha1(f"{self.embedder.model}|{self.embedder.dim}|{text}".encode()).hexdigest()

    def embed_query(self, text: str) -> list[float]:
        key = self._key(text)
        if key not in self.cache:
            self.cache[key] = self.embedder.embed_query(text)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(self._json.dumps(self.cache), encoding="utf-8")
        return self.cache[key]
