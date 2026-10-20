-- PostgreSQL + pgvector 스키마. {dim}은 init_schema에서 EMBEDDING_DIM으로 치환한다.
CREATE EXTENSION IF NOT EXISTS vector;

-- parent: 구조 단위(조항, 용어, 소제목 단락). 임베딩하지 않는다.
CREATE TABLE IF NOT EXISTS parent_chunks (
    experiment_id TEXT NOT NULL,
    parent_id     TEXT NOT NULL,
    chunk_method  TEXT NOT NULL,
    file_name     TEXT NOT NULL,
    doc_group     TEXT NOT NULL,
    page_no       INT  NOT NULL,
    page_end      INT  NOT NULL,
    section_title TEXT,
    content_type  TEXT NOT NULL,
    source_ids    TEXT[] NOT NULL DEFAULT '{}',
    content       TEXT NOT NULL,
    PRIMARY KEY (experiment_id, parent_id)
);

-- child(또는 Recursive 청크): 임베딩해서 검색한다.
CREATE TABLE IF NOT EXISTS chunks (
    experiment_id TEXT NOT NULL,
    chunk_id      TEXT NOT NULL,
    parent_id     TEXT,                    -- Recursive 방식은 NULL
    chunk_method  TEXT NOT NULL,
    file_name     TEXT NOT NULL,
    doc_group     TEXT NOT NULL,
    page_no       INT  NOT NULL,
    page_end      INT  NOT NULL,
    section_title TEXT,
    content_type  TEXT NOT NULL,
    source_ids    TEXT[] NOT NULL DEFAULT '{}',
    content       TEXT NOT NULL,
    embedding     vector({dim}) NOT NULL,
    PRIMARY KEY (experiment_id, chunk_id),
    FOREIGN KEY (experiment_id, parent_id) REFERENCES parent_chunks (experiment_id, parent_id)
);

CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw
    ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_experiment_idx ON chunks (experiment_id, doc_group);

-- 검색 평가 결과. run 1개 = (experiment, 검색기, 설정) 한 번 실행.
CREATE TABLE IF NOT EXISTS retrieval_eval_runs (
    run_id        TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL,
    retriever     TEXT NOT NULL,
    params        JSONB NOT NULL,
    metrics       JSONB NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS retrieval_eval_cases (
    run_id        TEXT NOT NULL REFERENCES retrieval_eval_runs (run_id) ON DELETE CASCADE,
    case_id       TEXT NOT NULL,
    question_set  TEXT NOT NULL,
    difficulty    TEXT,
    gold          TEXT[] NOT NULL,
    child_ranked  JSONB NOT NULL,   -- [{chunk_id, source_ids}] 순위순
    parent_ranked JSONB,            -- [{parent_id, source_ids}] (Parent-Child만)
    metrics       JSONB NOT NULL,
    PRIMARY KEY (run_id, case_id)
);

-- RAG 실행 기록. run 1개 = (파이프라인, 설정) 한 번 실행. 문항별 기록은 agent_traces.jsonl로도 내보낸다.
CREATE TABLE IF NOT EXISTS rag_runs (
    run_id     TEXT PRIMARY KEY,
    pipeline   TEXT NOT NULL,          -- basic_rag / multi_agent
    params     JSONB NOT NULL,
    summary    JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rag_case_results (
    run_id        TEXT NOT NULL REFERENCES rag_runs (run_id) ON DELETE CASCADE,
    case_id       TEXT NOT NULL,
    question_set  TEXT NOT NULL,
    question      TEXT NOT NULL,
    response_type TEXT,
    answer        TEXT,
    record        JSONB NOT NULL,      -- 인용, 검색 청크, trace, 사용량 전체
    checks        JSONB,               -- 코드 기반 1차 채점
    error         TEXT,
    PRIMARY KEY (run_id, case_id)
);
