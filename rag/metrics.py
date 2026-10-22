"""검색 지표. 검색 결과는 순위대로 나열한 source_ids 목록이고, 정답은 expected_source_ids 집합이다.

  Hit@k       : 상위 k개 중 정답 근거를 하나라도 포함한 청크가 있으면 1
  Recall@k    : 정답 근거 ID 중 상위 k개가 덮은 비율
  Precision@k : 상위 k개 중 정답 근거를 포함한 청크의 비율 (분모 k)
  MRR         : 정답을 포함한 첫 청크 순위의 역수
  nDCG@k      : 새 정답 근거를 처음 덮는 청크만 이득 1로 본다(같은 근거의 반복은 0).
                이상적인 순위는 정답 근거 수(최대 k)만큼 앞에 이득 1이 있는 경우다.
"""
from __future__ import annotations

import math


def ranking_metrics(ranked: list[list[str]], gold: set[str], ks=(1, 3, 5, 8, 10)) -> dict:
    relevant, gains, covered_at, seen = [], [], [], set()
    for ids in ranked:
        hit_ids = set(ids) & gold
        relevant.append(bool(hit_ids))
        new = hit_ids - seen
        gains.append(1.0 if new else 0.0)
        seen |= new
        covered_at.append(len(seen))
    first = next((i + 1 for i, r in enumerate(relevant) if r), None)
    out = {"mrr": 1.0 / first if first else 0.0}
    for k in ks:
        top = relevant[:k]
        out[f"hit@{k}"] = float(any(top))
        out[f"recall@{k}"] = (covered_at[min(k, len(covered_at)) - 1] / len(gold)) if covered_at else 0.0
        out[f"precision@{k}"] = sum(top) / k
        dcg = sum(g / math.log2(i + 2) for i, g in enumerate(gains[:k]))
        idcg = sum(1 / math.log2(i + 2) for i in range(min(k, len(gold))))
        out[f"ndcg@{k}"] = dcg / idcg if idcg else 0.0
    return out


def mean_metrics(rows: list[dict]) -> dict:
    if not rows:
        return {}
    return {key: sum(r[key] for r in rows) / len(rows) for key in rows[0]}
