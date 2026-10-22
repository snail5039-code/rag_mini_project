"""G1 검증: rag/llm.py의 오류 구분과 구조화 출력 재시도. 가짜 클라이언트라 API 비용이 없다.

    python scripts/test_g1_fault_tolerance.py
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google.genai import errors  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from rag import llm  # noqa: E402


class Out(BaseModel):
    answer: str


def resp(parsed, pt=10, ct=5):
    return SimpleNamespace(parsed=parsed, text="{broken", usage_metadata=SimpleNamespace(
        prompt_token_count=pt, candidates_token_count=ct))


class FakeClient:
    """calls를 세고, 준비한 응답(또는 예외)을 차례로 돌려준다."""

    def __init__(self, script):
        self.script, self.calls = list(script), 0
        self.models = self

    def generate_content(self, **kw):
        self.calls += 1
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def run(script):
    fake = FakeClient(script)
    llm._CLIENT = fake
    try:
        return fake, llm.generate_structured("s", "u", Out), None
    except Exception as e:  # noqa: BLE001
        return fake, None, e


results = []


def check(name, cond, detail=""):
    results.append(cond)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


# 1. 정상: 1번 호출, 반환값·사용량이 기존과 같다
fake, out, err = run([resp(Out(answer="ok"), 100, 20)])
check("정상 경로", fake.calls == 1 and out[0].answer == "ok" and out[1] == {"model_calls": 1, "input_tokens": 100, "output_tokens": 20},
      f"calls={fake.calls} usage={out[1] if out else err}")

# 2. 402: 즉시 FatalLLMError, 재호출 없음
for code in (401, 402, 403):
    fake, out, err = run([errors.APIError(code, {"error": {"message": "x", "status": "S"}})])
    check(f"{code}는 즉시 중단", isinstance(err, llm.FatalLLMError) and fake.calls == 1, f"calls={fake.calls} err={type(err).__name__}")

# 3. 그 밖의 API 오류(예: 400): FatalLLMError가 아니고 그대로 올라온다(SDK 재시도는 별도)
fake, out, err = run([errors.APIError(400, {"error": {"message": "bad", "status": "S"}})])
check("400은 일반 오류로 전파", isinstance(err, errors.APIError) and not isinstance(err, llm.FatalLLMError) and fake.calls == 1)

# 4. 파싱 실패 후 정상: 2번 호출, 사용량 합산
fake, out, err = run([resp(None, 50, 7), resp(Out(answer="ok"), 60, 8)])
check("파싱 실패 후 재호출 성공", fake.calls == 2 and out and out[1] == {"model_calls": 2, "input_tokens": 110, "output_tokens": 15},
      f"calls={fake.calls} usage={out[1] if out else err}")

# 5. 파싱 실패 2번: ValueError
fake, out, err = run([resp(None), resp(None)])
check("파싱 실패 2번은 ValueError", isinstance(err, ValueError) and fake.calls == 2, f"calls={fake.calls} err={type(err).__name__}")

# 6. run_rag: FatalLLMError가 나오면 남은 문항은 호출 없이 건너뛴다 (가짜 파이프라인, workers=1)
import io  # noqa: E402
from contextlib import redirect_stdout  # noqa: E402

import scripts.run_rag as rr  # noqa: E402

calls = {"n": 0}


class FakeRAG:
    pipeline = "basic_rag"
    conn = None

    def __init__(self, *a, **k):
        pass

    def params(self):
        return {}

    def run(self, q, qs):
        calls["n"] += 1
        raise llm.FatalLLMError("402: credit")


class FakeEmbedder:
    def embed_query(self, t):
        return [0.0]


rr.BasicRAG, rr.CachedQueryEmbedder = FakeRAG, FakeEmbedder
sys.argv = ["run_rag.py", "--pipeline", "basic", "--sets", "negative", "--limit", "12", "--workers", "1", "--no-save"]
buf = io.StringIO()
with redirect_stdout(buf):
    rr.main()
out_text = buf.getvalue()
check("중지 플래그: 첫 오류 뒤 호출 0건", calls["n"] == 1 and "오류 12개" in out_text,
      f"calls={calls['n']} errors_in_output={'오류 12개' in out_text}")

print(f"\n{sum(results)}/{len(results)} 통과")
sys.exit(0 if all(results) else 1)
