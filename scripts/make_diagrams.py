"""docs/images/*.svg 도식 생성. PNG는 브라우저로 렌더링한다 (예: Chrome --headless --screenshot).

  python scripts/make_diagrams.py
"""
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parent.parent / "docs" / "images"
OUT.mkdir(parents=True, exist_ok=True)

FONT = "'Apple SD Gothic Neo','Noto Sans KR','Malgun Gothic',sans-serif"
C = {
    "blue": ("#E8F1FD", "#3B82F6"),
    "green": ("#E7F6EC", "#22A06B"),
    "orange": ("#FFF1E0", "#F08C1A"),
    "purple": ("#F1EAFB", "#8B5CF6"),
    "gray": ("#F3F4F6", "#6B7280"),
    "red": ("#FDECEC", "#DC4C4C"),
}
INK = "#1F2937"


class Svg:
    def __init__(self, w, h, title):
        self.w, self.h = w, h
        self.parts = []
        self.text(40, 38, title, size=21, weight="bold", anchor="start")

    def text(self, x, y, s, size=13, weight="normal", anchor="middle", fill=INK):
        self.parts.append(
            f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" '
            f'text-anchor="{anchor}" fill="{fill}">{escape(s)}</text>'
        )

    def frame(self, x, y, w, h, label):
        self.parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="#FAFBFC" '
            f'stroke="#9CA3AF" stroke-width="1.5" stroke-dasharray="3 4"/>'
        )
        self.text(x + w - 16, y + h - 8, label, size=13, weight="bold", anchor="end", fill="#4B5563")

    def box(self, x, y, w, h, title, lines=(), color="blue", dashed=False):
        fill, stroke = C[color]
        d = ' stroke-dasharray="6 4"' if dashed else ""
        self.parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="2"{d}/>'
        )
        cx = x + w / 2
        if lines:
            total = 20 + 19 * len(lines)
            top = y + (h - total) / 2 + 15
            self.text(cx, top, title, size=15, weight="bold")
            for i, ln in enumerate(lines):
                self.text(cx, top + 24 + 19 * i, ln, size=13)
        else:
            self.text(cx, y + h / 2 + 5, title, size=15, weight="bold")

    def line(self, pts):
        d = "M " + " L ".join(f"{x} {y}" for x, y in pts)
        self.parts.append(f'<path d="{d}" fill="none" stroke="#4B5563" stroke-width="2"/>')

    def arrow(self, pts, label=None, lpos=None, dashed=False, color="#4B5563"):
        d = "M " + " L ".join(f"{x} {y}" for x, y in pts)
        dash = ' stroke-dasharray="7 5"' if dashed else ""
        self.parts.append(
            f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2"{dash} marker-end="url(#ah)"/>'
        )
        if label:
            lx, ly = lpos
            self.text(lx, ly, label, size=12, fill="#374151")

    def save(self, name):
        head = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
            f'viewBox="0 0 {self.w} {self.h}" font-family="{FONT}">'
            '<defs><marker id="ah" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto">'
            '<path d="M0 0 L10 4 L0 8 z" fill="#4B5563"/></marker></defs>'
            f'<rect width="{self.w}" height="{self.h}" fill="#FFFFFF"/>'
        )
        (OUT / name).write_text(head + "".join(self.parts) + "</svg>", encoding="utf-8")


# ---------------------------------------------------------------- 1. overview
s = Svg(1200, 480, "전체 파이프라인 한눈에 보기")
s.box(40, 70, 300, 64, "01_data → 추출 JSONL", ["PDF 23개 → extracted_pages.jsonl"], "gray")
s.box(450, 70, 300, 64, "02_questions  (질문 JSON)", ["Agent에 들어가는 유일한 입력"], "gray")
s.box(860, 70, 300, 64, "03_answers + 골든셋", ["평가 전용 · 검색 DB/Agent에 넣지 않음"], "red")
for x in (190, 600, 1010):
    s.arrow([(x, 134), (x, 190)])
s.box(40, 190, 300, 130, "① 인덱싱 (오프라인)", ["추출 JSONL → parent / child 분할", "→ child 임베딩 → pgvector", "parent도 같은 PostgreSQL에 저장"], "blue")
s.box(450, 190, 300, 130, "② 질의 실행 (온라인)", ["질문 → 오케스트레이터", "검색 → 평가 Agent 판단", "→ (재검색) → 답변"], "green")
s.box(860, 190, 300, 130, "③ 기록 · 평가 루프", ["실행 기록 PostgreSQL 저장", "RAG Agent 평가 → 실패 분석", "→ 설정 개선 → 재평가"], "orange")
s.arrow([(340, 255), (450, 255)], "인덱스", (395, 245))
s.arrow([(750, 255), (860, 255)], "실행 기록", (805, 245))
s.arrow([(1010, 320), (1010, 395), (190, 395), (190, 320)], dashed=True)
s.text(600, 388, "개선: 청킹 · 검색 · Agent 설정을 바꿔 다시 실행 (기준 설정 대비 한 번에 하나만 변경)", size=13)
s.text(600, 440, "임베딩은 두 시점에서만 발생: 인덱싱 때 child 청크 1회 + 검색할 때 검색어 1회 (재검색마다 추가)", size=13, fill="#6B7280")
s.save("01_overview.svg")

# ---------------------------------------------------------------- 2. indexing
s = Svg(1200, 660, "① 인덱싱 파이프라인 (오프라인, 설정이 바뀔 때만 다시 실행)")
xs = [30, 260, 490, 720, 950]
s.box(xs[0], 70, 200, 120, "① 추출 결과 읽기", ["extracted_pages.jsonl", "(박의혁 추출 · 페이지 단위)", "file_name · page_no"], "gray")
s.box(xs[1], 70, 200, 120, "② 구조 인식", ["용어집: 용어 + 정의", "약관: 조항", "가이드: 소제목 + 문단", "표 · 차트: 영역 전체"], "blue")
s.box(xs[2], 70, 200, 120, "③ Parent 분할", ["② 단위가 곧 parent", "용어집은 parent = child 가능", "→ 답변 문맥으로 사용"], "orange")
s.box(xs[3], 70, 200, 120, "④ Child 분할", ["~300자 · 겹침 60", "제목 prefix 붙이기", "짧은 parent는 child와 동일", "→ 검색 단위"], "blue")
s.box(xs[4], 70, 200, 120, "⑤ 메타데이터 부여", ["chunk_id · parent_id", "file_name · page_no", "chunk_method · source_ids"], "purple")
for i in range(4):
    s.arrow([(xs[i] + 200, 130), (xs[i + 1], 130)])
s.box(950, 215, 200, 75, "근거 ID 매핑표", ["용어명 ↔ fsc-glossary-ID", "약관 파일 ↔ 약관번호·버전"], "gray", dashed=True)
s.arrow([(1050, 215), (1050, 190)], dashed=True)

s.frame(40, 386, 730, 176,"PostgreSQL + pgvector  (임베딩 모델·차원은 실험 전에 고정)")
# parent: ③ -> parent_chunks (no embedding)
s.arrow([(590, 190), (590, 270), (210, 270), (210, 412)])
s.text(400, 262, "parent는 임베딩하지 않고 그대로 저장", size=12)
# child: ④ -> bus -> chunks / bm25
s.arrow([(820, 190), (820, 320)])
s.arrow([(820, 320), (600, 320), (600, 412)], "임베딩 (child, 1회)", (700, 342))
s.arrow([(820, 320), (990, 320), (990, 412)], "읽어서 Kiwi 토큰화 (실험용)", (868, 342), dashed=True)
s.box(60, 412, 300, 130, "parent_chunks 테이블", ["parent 원문 + source_ids", "임베딩 없음", "parent_id로 조회"], "orange")
s.box(450, 412, 300, 130, "chunks 테이블 (pgvector)", ["child 청크 + embedding 컬럼", "HNSW 인덱스 · cosine", "기준 검색: Vector"], "green")
s.box(840, 412, 300, 130, "BM25 (실험용)", ["PostgreSQL의 child를 읽어", "메모리에서 구성", "같은 parent_id 유지"], "gray", dashed=True)
s.text(600, 592, "실험은 experiment_id · chunk_method 컬럼으로 구분하고, 이미 저장된 chunk_id는 재임베딩하지 않습니다.", size=13, fill="#6B7280")
s.text(600, 614, "저장 후 모든 child의 parent_id가 parent_chunks에 있는지 검증합니다.", size=13, fill="#6B7280")
s.text(600, 636, "청킹 비교: Recursive(300/500/800/1000, 겹침 60) vs Parent-Child. 같은 source_ids로 채점합니다.", size=13, fill="#6B7280")
s.save("02_indexing.svg")

# ---------------------------------------------------------------- 3. agent flow
s = Svg(1200, 730, "② 질의 실행 — 멀티 Agent 흐름 (문항마다 실행)")
s.box(40, 60, 150, 64, "질문", ["02_questions"], "gray")
s.box(230, 55, 930, 74, "오케스트레이터 Agent", ["공통 상태 · 실행 순서 · 반복 횟수(N) · 종료 조건 관리 / 모든 호출 수·토큰·시간 기록"], "purple")
s.arrow([(190, 92), (230, 92)])

s.box(40, 190, 280, 140, "검색 Agent", ["① 검색 범위(scope) 선택", "② 검색어 작성", "③ child 벡터 검색 (pgvector)", "④ parent_id로 parent 조회"], "blue")
s.box(400, 190, 240, 140, "평가 Agent", ["검색 결과로 답할 수", "있는지 평가", "→ 응답 유형 결정"], "orange")
s.arrow([(320, 260), (400, 260)], "검색 결과", (360, 250))
s.arrow([(135, 129), (135, 190)], "검색 요청", (95, 165))

s.box(760, 150, 400, 90, "충분 → 답변 Agent (3.7 Flash)", ["질문 요소 점검표 → 요소별 답변 + 파일명·페이지 인용", "종료 [answer / correct]"], "green")
s.box(760, 255, 400, 66, "질문이 모호함 → 되묻기", ["필요한 정보를 구체적으로 질문 · 종료 [clarify]"], "gray")
s.box(760, 336, 400, 66, "범위 밖 · 부적절 · 인젝션 → 보류 / 거절", ["빠진 정보 · 확인 불가 이유 · 확인처 안내 [abstain/refuse]"], "red")
s.box(760, 417, 400, 66, "재시도 횟수 소진 → 근거 부족 안내", ["종료 [abstain]"], "red")
for y in (195, 288, 369, 450):
    s.arrow([(640, 260), (700, 260), (700, y), (760, y)])

s.box(400, 470, 240, 90, "피드백 Agent", ["부족한 근거와", "검색 실패 원인 분석"], "orange")
s.box(40, 470, 280, 90, "개선 Agent", ["검색어 · 필터 · 검색 방식 수정"], "blue")
s.arrow([(520, 330), (520, 470)], "부족 (재시도 남음)", (610, 408))
s.arrow([(400, 515), (320, 515)])
s.arrow([(180, 470), (180, 330)], "재검색", (212, 405))
s.text(600, 610, "재검색은 최대 2회. 횟수를 소진하거나 새 근거가 없으면 '재시도 소진' 경로로 종료합니다.", size=13, fill="#6B7280")
s.text(600, 635, "문서 본문과 질문 속의 지시문은 따르지 않도록 프롬프트에서 지시 영역과 문서 영역을 분리합니다.", size=13, fill="#6B7280")
s.text(600, 660, "기준 검색은 Vector입니다. BM25 · Hybrid · MMR · max_parents는 비교 실험에서 하나씩 바꿉니다.", size=13, fill="#6B7280")
s.text(600, 685, "미들웨어: 검색 범위 강제 · 호출 횟수 제한 · 중복 검색 차단 · 인용 검증 · 구조화 로그(PostgreSQL)", size=13, fill="#6B7280")
s.save("03_agent_flow.svg")

# ---------------------------------------------------------------- 4. eval loop
s = Svg(1200, 690, "③ 기록 · 평가 루프 (실행 → 평가 → 분석 → 개선 → 재평가)")
s.box(30, 70, 250, 120, "① 실행", ["문항(case_id)을 하나씩", "Agent 파이프라인 실행", "같은 질문 · 같은 PDF 범위"], "blue")
s.box(340, 70, 250, 120, "② 실행 기록 저장", ["PostgreSQL, experiment_id로 연결", "답변 · 인용 · 검색 청크 · trace", "호출 수 · 토큰 · 시간"], "purple")
s.box(650, 70, 250, 120, "③ RAG Agent 평가", ["03_answers · 골든셋과 비교", "아래 5축으로 채점", "(골든셋 QA는 별도 담당)"], "orange")
s.arrow([(280, 130), (340, 130)])
s.arrow([(590, 130), (650, 130)])
s.arrow([(775, 190), (775, 235)])
bx = [30, 262, 494, 726, 958]
bw = 212
s.box(bx[0], 235, bw, 100, "검색", ["Hit@k · Recall@k · MRR", "nDCG@k (child + parent)"], "green")
s.box(bx[1], 235, bw, 100, "답변", ["정확성 · 완전성", "근거 충실성 · 인용 정확성"], "green")
s.box(bx[2], 235, bw, 100, "Negative", ["응답 유형이 기대 행동과", "맞는가 (되묻기·보류·거절)"], "green")
s.box(bx[3], 235, bw, 100, "Tool-use · Trajectory", ["도구 · 검색 범위 · 인자", "불필요한 재검색 여부"], "green")
s.box(bx[4], 235, bw, 100, "효율", ["호출 수 · 응답 시간", "토큰 · 비용"], "green")
for x in bx:
    s.line([(x + bw / 2, 335), (x + bw / 2, 358)])
s.line([(bx[0] + bw / 2, 358), (bx[4] + bw / 2, 358)])
s.arrow([(600, 358), (600, 380)])
s.box(30, 380, 1140, 40, "④ 실패 분석 — 원인 6종 중 어디인지 구분 (특히 검색 실패 vs 답변 실패)", [], "red")
fx = [30 + 194 * i for i in range(6)]
fails = [
    ("추출 실패", ["OCR · 표 · 이미지", "추출 개선"]),
    ("청킹 실패", ["크기 · 겹침", "문서 구조"]),
    ("검색 실패", ["검색기 · k", "필터 · max_parents"]),
    ("답변 실패", ["프롬프트", "생성 모델"]),
    ("인용 실패", ["페이지 메타데이터", "전달"]),
    ("Agent 실패", ["도구 · 검색어 ·", "평가 판단 · 종료"]),
]
for x, (t, ls) in zip(fx, fails):
    s.arrow([(x + 85, 420), (x + 85, 450)])
    s.box(x, 450, 170, 90, t, ls, "red")
    s.arrow([(x + 85, 540), (x + 85, 580)])
s.box(30, 580, 1140, 70, "⑤ 개선 → 재평가", ["기준 설정 대비 한 요소만 변경 → 새 experiment_id → 같은 질문으로 다시 실행"], "blue")
s.arrow([(30, 615), (12, 615), (12, 130), (30, 130)], dashed=True)
s.save("04_eval_loop.svg")
print("ok")
