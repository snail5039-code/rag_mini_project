"""검색기: Vector(기준) / BM25 / Hybrid(RRF) / MMR, 그리고 child -> parent 조회.

모든 검색기는 같은 형식의 결과(child 청크 dict 목록, 순위순)를 돌려준다.
  retriever = make_retriever("hybrid", conn, experiment_id)
  children = retriever.search(query_text, query_vec, k=10)
  parents = fetch_parents(conn, experiment_id, children, max_parents=5)
"""
from __future__ import annotations

import numpy as np
import psycopg

_CHUNK_COLS = ("chunk_id, parent_id, file_name, doc_group, page_no, page_end, section_title, "
               "content_type, source_ids, content")


def _rows(cur) -> list[dict]:
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def vector_search(conn: psycopg.Connection, query_vec, experiment_id: str, child_k: int = 8,
                  scope_files: list[str] | None = None, with_embedding: bool = False) -> list[dict]:
    """상위 child_k개 청크. distance는 cosine 거리(작을수록 가깝다)."""
    extra = ", embedding" if with_embedding else ""
    sql = f"""SELECT {_CHUNK_COLS}{extra}, embedding <=> %(q)s::vector AS distance
              FROM chunks
              WHERE experiment_id = %(exp)s AND (%(files)s::text[] IS NULL OR file_name = ANY(%(files)s))
              ORDER BY embedding <=> %(q)s::vector
              LIMIT %(k)s"""
    cur = conn.execute(sql, {"q": np.asarray(query_vec, dtype=np.float32), "exp": experiment_id,
                             "files": scope_files, "k": child_k})
    return _rows(cur)


def fetch_parents(conn: psycopg.Connection, experiment_id: str, children: list[dict],
                  max_parents: int = 5) -> list[dict]:
    """검색 순서를 유지하며 parent_id를 중복 제거하고 parent를 조회한다."""
    order: list[str] = []
    for c in children:
        pid = c["parent_id"]
        if pid and pid not in order:
            order.append(pid)
        if len(order) == max_parents:
            break
    if not order:
        return []
    cur = conn.execute(
        """SELECT parent_id, file_name, page_no, page_end, section_title, content_type, source_ids, content
           FROM parent_chunks WHERE experiment_id = %s AND parent_id = ANY(%s)""",
        (experiment_id, order),
    )
    by_id = {r["parent_id"]: r for r in _rows(cur)}
    missing = set(order) - set(by_id)
    if missing:
        raise ValueError(f"parent_chunks에 없는 parent_id: {sorted(missing)[:3]}")
    return [by_id[pid] for pid in order]


# ------------------------------------------------------------------ 검색기
class VectorRetriever:
    name = "vector"

    def __init__(self, conn, experiment_id: str):
        self.conn, self.experiment_id = conn, experiment_id

    def search(self, query: str, query_vec, k: int = 10, scope_files=None) -> list[dict]:
        return vector_search(self.conn, query_vec, self.experiment_id, k, scope_files)


_KIWI = None


def kiwi_tokenize(text: str) -> list[str]:
    """명사·동사·수식언·어근·외국어·숫자만 남긴다(노트북 09·10과 같은 기준)."""
    global _KIWI
    if _KIWI is None:
        from kiwipiepy import Kiwi
        _KIWI = Kiwi()
    return [t.form.lower() for t in _KIWI.tokenize(text)
            if t.tag.startswith(("N", "V", "M", "X")) or t.tag in {"SL", "SN"}]


class BM25Retriever:
    """experiment의 child 전체를 PostgreSQL에서 읽어 메모리에 BM25 인덱스를 만든다."""
    name = "bm25"

    def __init__(self, conn, experiment_id: str):
        from rank_bm25 import BM25Okapi

        self.experiment_id = experiment_id
        cur = conn.execute(f"SELECT {_CHUNK_COLS} FROM chunks WHERE experiment_id = %s ORDER BY chunk_id",
                           (experiment_id,))
        self.docs = _rows(cur)
        corpus = [kiwi_tokenize(f"{d['section_title'] or ''}\n{d['content']}") for d in self.docs]
        self.bm25 = BM25Okapi(corpus)

    def search(self, query: str, query_vec=None, k: int = 10, scope_files=None) -> list[dict]:
        scores = self.bm25.get_scores(kiwi_tokenize(query))
        if scope_files:
            allowed = set(scope_files)
            scores = np.where([d["file_name"] in allowed for d in self.docs], scores, -np.inf)
        top = np.argsort(-scores)[:k]
        return [{**self.docs[i], "bm25_score": float(scores[i])} for i in top if scores[i] > 0]


class HybridRetriever:
    """Vector와 BM25 순위를 RRF로 결합한다. score = Σ weight / (rrf_k + rank)."""
    name = "hybrid"

    def __init__(self, vector: VectorRetriever, bm25: BM25Retriever, weights=(0.5, 0.5),
                 rrf_k: int = 60, fetch_k: int = 20):
        self.vector, self.bm25 = vector, bm25
        self.weights, self.rrf_k, self.fetch_k = weights, rrf_k, fetch_k

    def search(self, query: str, query_vec, k: int = 10, scope_files=None) -> list[dict]:
        fused: dict[str, float] = {}
        docs: dict[str, dict] = {}
        lists = (self.vector.search(query, query_vec, self.fetch_k, scope_files),
                 self.bm25.search(query, None, self.fetch_k, scope_files))
        for weight, results in zip(self.weights, lists):
            for rank, d in enumerate(results, start=1):
                fused[d["chunk_id"]] = fused.get(d["chunk_id"], 0.0) + weight / (self.rrf_k + rank)
                docs.setdefault(d["chunk_id"], d)
        order = sorted(fused, key=fused.get, reverse=True)[:k]
        return [{**docs[cid], "rrf_score": fused[cid]} for cid in order]


class MMRRetriever:
    """Vector 후보 fetch_k개에서 관련성과 중복을 함께 보고 k개를 고른다. 저장된 벡터를 쓴다(재임베딩 없음)."""
    name = "mmr"

    def __init__(self, conn, experiment_id: str, lambda_mult: float = 0.7, fetch_k: int = 20):
        self.conn, self.experiment_id = conn, experiment_id
        self.lambda_mult, self.fetch_k = lambda_mult, fetch_k

    def search(self, query: str, query_vec, k: int = 10, scope_files=None) -> list[dict]:
        cands = vector_search(self.conn, query_vec, self.experiment_id, self.fetch_k, scope_files,
                              with_embedding=True)
        if not cands:
            return []
        mat = np.array([np.asarray(c["embedding"].to_numpy(), dtype=np.float32) for c in cands])
        mat /= np.linalg.norm(mat, axis=1, keepdims=True)
        q = np.asarray(query_vec, dtype=np.float32)
        q /= np.linalg.norm(q)
        rel = mat @ q
        sim = mat @ mat.T
        chosen = [int(np.argmax(rel))]
        while len(chosen) < min(k, len(cands)):
            rest = [i for i in range(len(cands)) if i not in chosen]
            score = [self.lambda_mult * rel[i] - (1 - self.lambda_mult) * sim[i, chosen].max() for i in rest]
            chosen.append(rest[int(np.argmax(score))])
        return [{key: v for key, v in cands[i].items() if key != "embedding"} for i in chosen]


def make_retriever(name: str, conn, experiment_id: str, **kwargs):
    if name == "vector":
        return VectorRetriever(conn, experiment_id)
    if name == "bm25":
        return BM25Retriever(conn, experiment_id)
    if name == "hybrid":
        return HybridRetriever(VectorRetriever(conn, experiment_id), BM25Retriever(conn, experiment_id), **kwargs)
    if name == "mmr":
        return MMRRetriever(conn, experiment_id, **kwargs)
    raise ValueError(f"알 수 없는 검색기: {name}")
