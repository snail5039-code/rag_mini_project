"""경로와 청킹·임베딩 설정. 값은 기준 설정이며 실험으로 바꾼다."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXTRACTED_PATH = ROOT / "04_extracted" / "extracted_pages.jsonl"
ANSWERS_DIR = ROOT / "03_answers"
CHUNK_DIR = ROOT / "05_chunks"

# --- 청킹 ---------------------------------------------------------------
CHILD_SIZE = 300          # Parent-Child의 child 크기
CHILD_OVERLAP = 60
RECURSIVE_SIZES = (300, 500, 800, 1000)   # Recursive 비교 설정 (겹침은 공통)
RECURSIVE_OVERLAP = 60
SEPARATORS = ["\n\n", "\n", " ", ""]

# 가이드·추가 PDF의 소제목 단위 parent가 너무 짧거나 길 때의 보정
MIN_PARENT_CHARS = 200
MAX_PARENT_CHARS = 2500

# 문서 표시용 이름 (section_title 앞에 붙는다)
DOC_TITLES = {
    "financial_life_guide": "금융생활 가이드북",
    "housing_pension_2026": "2026 주택연금 백문백답",
    "housing_policy_finance_2025": "주택 정책금융 2025",
    "insurance_terms_example_2020": "보험약관 예시 2020",
    "policy_finance_debt_adjustment_2026": "정책서민금융·채무조정 2026",
    "retirement_pension_2025": "퇴직연금 2025",
    "self_employed_debt_2025": "자영업자 채무 2025",
}
LIFE_GUIDE_KEY = "fss-life-guide"   # 기준 답안의 근거 ID 접두어

# --- 임베딩 (모델·차원은 실험 시작 전에 하나로 고정한다) ------------------
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "gemini-embedding-2")
# pgvector의 vector 타입 HNSW 인덱스는 약 2,000차원까지만 지원한다.
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1536"))

# --- 답변 생성 -------------------------------------------------------------
GENERATION_MODEL = os.getenv("GENERATION_MODEL", "gemini-3.6-flash")
# Multi-Agent의 답변 Agent만 쓰는 모델. 270문항 3회에서 Judge 정확성 0.864(3.6-flash) -> 0.887(3.7-flash)
ANSWER_MODEL = os.getenv("ANSWER_MODEL", "gemini-3.7-flash")

# --- 검색 기준 설정 (eval_retrieval 비교 결과로 확정) ----------------------
BASELINE_EXPERIMENT = os.getenv(
    "BASELINE_EXPERIMENT", f"parent_child_300_60__{EMBEDDING_MODEL}_{EMBEDDING_DIM}")
CHILD_K = 8
MAX_PARENTS = 5

# 질문 세트별 검색 범위 (README: 기본 positive/negative는 용어집+약관만 검색)
SCOPE_GROUPS = {
    "base": ("glossary", "standard_terms"),
    "negative": ("glossary", "standard_terms"),
    "life": ("life_guide",),
    "add": ("additional",),
}
