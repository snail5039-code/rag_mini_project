"""PostgreSQL에 rag 데이터베이스와 pgvector 스키마를 만든다. 여러 번 실행해도 안전하다.

  python scripts/init_db.py
"""
import os
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg
from psycopg import sql

from rag import config, db


def main() -> None:
    target = os.getenv("POSTGRES_DB", "rag")
    user = quote(os.getenv("POSTGRES_USER", "postgres"), safe="")
    password = quote(os.getenv("POSTGRES_PASSWORD", ""), safe="")
    admin_url = f"postgresql://{user}:{password}@localhost:5432/postgres"

    with psycopg.connect(admin_url, autocommit=True) as admin:
        exists = admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target,)).fetchone()
        if not exists:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target)))
            print(f"데이터베이스 생성: {target}")
        else:
            print(f"데이터베이스 있음: {target}")

    conn = db.connect()
    db.init_schema(conn, config.EMBEDDING_DIM)
    ext = conn.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'").fetchone()
    print(f"pgvector 확장 버전: {ext[0]}")
    tables = [r[0] for r in conn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1").fetchall()]
    print("테이블:", tables)
    dist = conn.execute("SELECT '[1,0,0]'::vector <=> '[0,1,0]'::vector").fetchone()[0]
    print(f"cosine 거리 연산 확인: {dist}")


if __name__ == "__main__":
    main()
