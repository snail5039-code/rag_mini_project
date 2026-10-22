"""PostgreSQL + pgvector 연결과 적재."""
from __future__ import annotations

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from pgvector.psycopg import register_vector

from . import config

load_dotenv(config.ROOT / ".env")
SCHEMA_PATH = config.ROOT / "db" / "schema.sql"


def database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    from urllib.parse import quote
    user = quote(os.getenv("POSTGRES_USER", "postgres"), safe="")
    password = os.getenv("POSTGRES_PASSWORD")
    if not password:
        raise ValueError(".env에 POSTGRES_PASSWORD(또는 DATABASE_URL)를 설정하세요.")
    db = os.getenv("POSTGRES_DB", "rag")
    return f"postgresql://{user}:{quote(password, safe='')}@localhost:5432/{db}"


def connect() -> psycopg.Connection:
    # vector 확장은 init_schema에서 만든다(여러 스레드가 동시에 CREATE EXTENSION을 하면 충돌한다).
    conn = psycopg.connect(database_url(), autocommit=True)
    register_vector(conn)
    return conn


def init_schema(conn: psycopg.Connection, dim: int = config.EMBEDDING_DIM) -> None:
    conn.execute(Path(SCHEMA_PATH).read_text(encoding="utf-8").replace("{dim}", str(dim)))


def existing_chunk_ids(conn: psycopg.Connection, experiment_id: str) -> set[str]:
    rows = conn.execute("SELECT chunk_id FROM chunks WHERE experiment_id = %s", (experiment_id,)).fetchall()
    return {r[0] for r in rows}


def insert_parents(conn: psycopg.Connection, experiment_id: str, parents: list[dict]) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO parent_chunks (experiment_id, parent_id, chunk_method, file_name, doc_group,
                   page_no, page_end, section_title, content_type, source_ids, content)
               VALUES (%(experiment_id)s, %(parent_id)s, %(chunk_method)s, %(file_name)s, %(doc_group)s,
                   %(page_no)s, %(page_end)s, %(section_title)s, %(content_type)s, %(source_ids)s, %(content)s)
               ON CONFLICT (experiment_id, parent_id) DO NOTHING""",
            [{**p, "experiment_id": experiment_id} for p in parents],
        )


def insert_chunks(conn: psycopg.Connection, experiment_id: str, chunks: list[dict], vectors: list[list[float]]) -> None:
    if len(chunks) != len(vectors):
        raise ValueError(f"청크 수({len(chunks)})와 벡터 수({len(vectors)})가 다릅니다.")
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO chunks (experiment_id, chunk_id, parent_id, chunk_method, file_name, doc_group,
                   page_no, page_end, section_title, content_type, source_ids, content, embedding)
               VALUES (%(experiment_id)s, %(chunk_id)s, %(parent_id)s, %(chunk_method)s, %(file_name)s,
                   %(doc_group)s, %(page_no)s, %(page_end)s, %(section_title)s, %(content_type)s,
                   %(source_ids)s, %(content)s, %(embedding)s)
               ON CONFLICT (experiment_id, chunk_id) DO NOTHING""",
            [{**c, "experiment_id": experiment_id, "embedding": v} for c, v in zip(chunks, vectors)],
        )


def check_integrity(conn: psycopg.Connection, experiment_id: str) -> int:
    """parent_id가 있는데 parent_chunks에 없는 child 수 (0이어야 한다)."""
    row = conn.execute(
        """SELECT count(*) FROM chunks c LEFT JOIN parent_chunks p
               ON p.experiment_id = c.experiment_id AND p.parent_id = c.parent_id
           WHERE c.experiment_id = %s AND c.parent_id IS NOT NULL AND p.parent_id IS NULL""",
        (experiment_id,),
    ).fetchone()
    return row[0]
