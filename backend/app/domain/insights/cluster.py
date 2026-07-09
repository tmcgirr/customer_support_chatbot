"""Deterministic question clustering (the 'pre-group' half of the hybrid engine).

Groups questions whose embeddings are near-identical into connected components of a
cosine-similarity graph (edge when cosine ≥ threshold). Pure Python, no numpy — a daily
job over a capped batch (a few hundred short questions) runs in well under a second.

Deterministic and ORDER-INDEPENDENT (union-find over all pairs), so the same inputs always
yield the same clusters — which keeps the report stable and the tests simple. The LLM then
names/analyzes each cluster (``labeler``/pipeline), never the grouping itself.
"""

import math


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector))
    if norm == 0.0:
        return vector
    return [x / norm for x in vector]


def _cosine(a: list[float], b: list[float]) -> float:
    # a and b are already unit-normalized, so cosine == dot product.
    return sum(x * y for x, y in zip(a, b, strict=True))


def cluster_by_similarity(embeddings: list[list[float]], *, threshold: float) -> list[list[int]]:
    """Return clusters of indices whose pairwise cosine similarity ≥ ``threshold``,
    largest first (ties broken by smallest member index). Every index appears in exactly
    one cluster; a question similar to nothing else is its own singleton cluster."""
    n = len(embeddings)
    if n == 0:
        return []
    normed = [_normalize(v) for v in embeddings]

    parent = list(range(n))

    def find(i: int) -> int:
        root = i
        while parent[root] != root:
            root = parent[root]
        while parent[i] != root:  # path compression
            parent[i], i = root, parent[i]
        return root

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[max(ri, rj)] = min(ri, rj)

    for i in range(n):
        for j in range(i + 1, n):
            if _cosine(normed[i], normed[j]) >= threshold:
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return sorted(groups.values(), key=lambda g: (-len(g), g[0]))
