"""cluster_by_similarity: pure, deterministic, order-independent grouping of near-identical
question embeddings into connected components of a cosine-similarity graph."""

from app.domain.insights.cluster import cluster_by_similarity


def test_empty_input() -> None:
    assert cluster_by_similarity([], threshold=0.8) == []


def test_identical_vectors_group_singletons_split() -> None:
    # Two near-identical (a, a') + one orthogonal (b).
    a = [1.0, 0.0]
    a2 = [0.99, 0.14]  # cosine with a ≈ 0.99
    b = [0.0, 1.0]  # orthogonal to a
    clusters = cluster_by_similarity([a, a2, b], threshold=0.8)
    # Largest first: {0,1} then the singleton {2}.
    assert clusters == [[0, 1], [2]]


def test_threshold_is_respected() -> None:
    a = [1.0, 0.0]
    slightly = [0.9, 0.436]  # cosine ≈ 0.90
    # A strict threshold keeps them apart; a looser one merges them.
    assert cluster_by_similarity([a, slightly], threshold=0.95) == [[0], [1]]
    assert cluster_by_similarity([a, slightly], threshold=0.85) == [[0, 1]]


def test_transitive_grouping_is_order_independent() -> None:
    # a~b and b~c (but a and c less similar) still land in ONE component via b.
    a = [1.0, 0.0]
    b = [0.94, 0.34]  # ~a and ~c
    c = [0.77, 0.64]  # ~b, weaker to a
    clusters = cluster_by_similarity([a, b, c], threshold=0.8)
    assert clusters == [[0, 1, 2]]


def test_zero_vector_does_not_crash_and_is_its_own_cluster() -> None:
    clusters = cluster_by_similarity([[0.0, 0.0], [1.0, 0.0]], threshold=0.5)
    assert sorted(sorted(c) for c in clusters) == [[0], [1]]
