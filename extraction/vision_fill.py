"""Gemini Vision 단계: needs_vision 블록(복잡한 표·차트·그림)을 이미지로 해석해 text 를 채운다.

extract_pdfs.py 실행 후 실행한다. 04_extracted/pages/*.jsonl 을 갱신하고 extracted_pages.jsonl 을 다시 합친다.
결과는 이미지 해시로 캐시(04_extracted/vision_cache/)하므로 재실행 시 이미 처리한 블록은 API 를 호출하지 않는다.

  python extraction/vision_fill.py              # 전체
  python extraction/vision_fill.py --limit 5    # 시험용 5개만
"""

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract_pdfs as E  # noqa: E402

MODEL = os.environ.get("GEMINI_VISION_MODEL", "gemini-3.5-flash")
PROMPT_VERSION = "v1"
CACHE_DIR = E.OUT_DIR / "vision_cache"
DECORATIVE = "DECORATIVE"
# OCR 로 읽은 글 영역은 OCR 결과 자체를 바로잡는 것이 목적이라 힌트를 주지 않는다
# (힌트를 주면 'Ⅲ'을 OCR 이 잘못 읽은 'Ⅱ'로 따라 쓰는 문제가 있었다)
NO_HINT_TYPES = {"text", "title", "caption"}

COMMON = (
    "너는 한국어 금융 문서의 이미지 영역을 검색용 텍스트로 옮기는 도구다. "
    "이미지에 보이는 내용만 쓰고, 보이지 않는 숫자·내용을 추측하거나 보충하지 마라. "
    "읽을 수 없는 부분은 [판독불가]로 표시하라. 설명 문장이나 머리말 없이 결과만 출력하라."
)
PROMPTS = {
    "table": COMMON + (
        " 이 이미지는 표다. 원문 그대로 Markdown 표로 변환하라. 병합 셀은 해당 칸마다 같은 값을 반복해 채워라. "
        "표 제목, 단위(예: 억원, %), 각주·주석·자료 출처가 보이면 표 위아래에 그대로 적어라."
    ),
    "chart": COMMON + (
        " 이 이미지는 차트다. 다음 순서로 적어라: 1) 차트 제목 2) 차트 종류, 축 이름과 단위, 범례 "
        "3) 그래프에 표시된 데이터 값을 Markdown 표로(값이 표기되지 않은 경우 눈금으로 읽은 근사값은 '약'을 붙여라) "
        "4) 차트가 보여 주는 추세를 1~2문장으로 5) 주석·자료 출처."
    ),
    "image": COMMON + (
        " 이 이미지가 정보를 담은 그림(도식, 절차도, 인포그래픽, 표 형태 그림, 글자가 있는 그림)이면 "
        "그림 속 글자를 빠짐없이 옮기고 흐름·관계를 한국어로 정리하라. "
        f"사진, 장식, 아이콘, 로고, 캐릭터처럼 검색에 쓸 정보가 없으면 {DECORATIVE} 한 단어만 출력하라."
    ),
}


def select:
    pass


# 텍스트 레이어가 없어 OCR 로 읽은 글 영역: 띄어쓰기·로마숫자(Ⅰ, Ⅱ) 등을 바로잡아 그대로 옮겨 적기
PROMPTS["text"] = PROMPTS["title"] = PROMPTS["caption"] = COMMON + (
    " 이 이미지는 문서의 글 영역이다. 보이는 글자를 줄바꿈과 띄어쓰기까지 원문 그대로 옮겨 적어라. "
    "요약하거나 설명을 덧붙이지 마라."
)

log = logging.getLogger("vision")


def load_env():
    env = E.ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def cache_key(img_bytes, btype):
    h = hashlib.sha256(img_bytes)
    h.update(f"|{btype}|{MODEL}|{PROMPT_VERSION}".encode())
    if btype in NO_HINT_TYPES:
        h.update(b"|nohint")  # 힌트 없는 프롬프트로 바뀐 글 영역만 캐시를 새로 만든다
    return h.hexdigest()


def call_gemini(client, img_bytes, btype, hint):
    from google.genai import types
    prompt = PROMPTS[btype]
    if hint and btype not in NO_HINT_TYPES:
        # 텍스트 레이어/OCR 로 얻은 글자는 철자 확인용 참고로만 준다
        prompt += "\n\n참고(같은 영역에서 기계적으로 추출한 글자, 순서·띄어쓰기가 틀릴 수 있음):\n" + hint[:3000]
    for attempt in range(5):
        try:
            resp = client.models.generate_content(
                model=MODEL,
                contents=[types.Part.from_bytes(data=img_bytes, mime_type="image/png"), prompt],
                config=types.GenerateContentConfig(temperature=0),
            )
            usage = resp.usage_metadata
            return (resp.text or "").strip(), {
                "input_tokens": getattr(usage, "prompt_token_count", None),
                "output_tokens": getattr(usage, "candidates_token_count", None),
            }
        except Exception as e:  # 429·5xx 등은 지수 백오프 후 재시도
            wait = 2 ** attempt * 3
            log.warning("Gemini 오류(%d회차) %s -> %ds 후 재시도", attempt + 1, str(e)[:200], wait)
            time.sleep(wait)
    raise RuntimeError("Gemini 호출 5회 실패")


def process(client, blk):
    img_path = E.OUT_DIR / blk["image_path"]
    img_bytes = img_path.read_bytes()
    key = cache_key(img_bytes, blk["type"])
    cache = CACHE_DIR / f"{key}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8")), True
    t0 = time.perf_counter()
    text, usage = call_gemini(client, img_bytes, blk["type"], blk.get("text", ""))
    res = {"text": text, "model": MODEL, "prompt_version": PROMPT_VERSION,
           "elapsed_sec": round(time.perf_counter() - t0, 2), **usage}
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    return res, False


def apply(blk, res):
    blk["pre_vision_text"] = blk.get("text", "")
    blk["pre_vision_source"] = blk.get("source")
    blk["vision"] = {k: res.get(k) for k in ("model", "prompt_version", "input_tokens", "output_tokens")}
    if res["text"].strip().upper() == DECORATIVE:
        blk["vision"]["result"] = "decorative"  # 정보 없는 그림: 기존 텍스트 유지
    else:
        blk["vision"]["result"] = "ok"
        blk["text"] = res["text"]
        blk["source"] = "gemini_vision"
    blk["needs_vision"] = False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--redo-types", default="", help="이미 Vision 처리된 블록 중 다시 처리할 type (쉼표 구분)")
    args = ap.parse_args()

    E.LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s",
                        handlers=[logging.FileHandler(E.LOG_PATH, encoding="utf-8"), logging.StreamHandler(sys.stdout)])
    for noisy in ("httpx", "google_genai", "google"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    load_env()
    from google import genai
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY") or os.environ["GOOGLE_API_KEY"])

    parts = sorted(E.PAGES_DIR.rglob("*.jsonl"))
    docs = {p: [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] for p in parts}
    redo = {t for t in args.redo_types.split(",") if t}
    for recs in docs.values():
        for r in recs:
            for blk in r["blocks"]:
                if redo and blk.get("vision") and blk["type"] in redo:  # Vision 이전 상태로 되돌려 재처리
                    blk["text"], blk["source"] = blk.pop("pre_vision_text"), blk.pop("pre_vision_source")
                    blk.pop("vision")
                    blk["needs_vision"] = True
    todo = [(p, blk) for p, recs in docs.items() for r in recs for blk in r["blocks"]
            if blk.get("needs_vision") and blk.get("image_path")]
    if args.limit:
        todo = todo[:args.limit]
    log.info("Vision 대상 %d개 (model=%s)", len(todo), MODEL)

    done = cached = failed = 0
    tok_in = tok_out = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(process, client, blk): (p, blk) for p, blk in todo}
        for f in as_completed(futs):
            p, blk = futs[f]
            try:
                res, hit = f.result()
                apply(blk, res)
                done += 1
                cached += hit
                if not hit:
                    tok_in += res.get("input_tokens") or 0
                    tok_out += res.get("output_tokens") or 0
            except Exception as e:
                failed += 1
                blk["vision_error"] = str(e)[:300]
                log.error("Vision 실패 %s: %s", blk.get("block_id"), e)
            if (done + failed) % 20 == 0:
                log.info("진행 %d/%d", done + failed, len(todo))

    for p, recs in docs.items():
        E.write_jsonl(p, recs)
    E.merge_all()
    log.info("Vision 완료 ok=%d (cache %d) failed=%d input_tokens=%d output_tokens=%d",
             done, cached, failed, tok_in, tok_out)


if __name__ == "__main__":
    main()
