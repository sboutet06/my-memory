"""Pure-logic tests for alias clustering."""
from __future__ import annotations

import numpy as np

from extraction.alias import (
    cluster_entities,
    normalize_name,
    pick_canonical,
)


def test_normalize_strips_accents_case_whitespace() -> None:
    assert normalize_name("  Sébastien  Boutet  ") == "sebastien boutet"


def test_normalize_handles_multiple_accents() -> None:
    assert normalize_name("Société à Côté") == "societe a cote"


def test_normalize_empty() -> None:
    assert normalize_name("") == ""
    assert normalize_name("   ") == ""


def test_pick_canonical_longest_wins() -> None:
    cluster = ["Sébastien Boutet", "Sébastien Jean Christophe Boutet", "Sebastien B."]
    assert pick_canonical(cluster) == "Sébastien Jean Christophe Boutet"


def test_pick_canonical_tie_breaks_alphabetically() -> None:
    assert pick_canonical(["Zoe", "Alice"]) == "Alice"


def _emb(vec: list[float]) -> np.ndarray:
    a = np.array(vec, dtype=np.float32)
    norm = np.linalg.norm(a)
    return a / norm if norm else a


def test_clusters_same_type_above_threshold() -> None:
    names = ["Alice", "Alice Smith", "Bob"]
    types = ["person", "person", "person"]
    # Close vectors for the two Alices; Bob is orthogonal.
    embs = np.array([_emb([1, 0]), _emb([0.97, 0.05]), _emb([0, 1])])
    clusters = cluster_entities(names, embs, types, threshold=0.85)
    # One multi-member cluster (Alices) + Bob singleton.
    non_singleton = [c for c in clusters if len(c) > 1]
    assert len(non_singleton) == 1
    assert set(non_singleton[0]) == {"Alice", "Alice Smith"}


def test_does_not_cluster_across_types() -> None:
    names = ["Alice", "Alice"]
    types = ["person", "organization"]
    embs = np.array([_emb([1, 0]), _emb([1, 0])])  # identical embeddings
    clusters = cluster_entities(names, embs, types, threshold=0.5)
    assert all(len(c) == 1 for c in clusters), clusters


def test_respects_type_filter() -> None:
    names = ["3370€", "3 370 €"]
    types = ["amount", "amount"]
    embs = np.array([_emb([1, 0]), _emb([1, 0])])
    # `amount` not in the cluster-allowed set — no merging.
    clusters = cluster_entities(
        names, embs, types, threshold=0.5,
        clusterable_types={"person", "organization"},
    )
    assert all(len(c) == 1 for c in clusters)


def test_returns_empty_for_empty_input() -> None:
    clusters = cluster_entities([], np.zeros((0, 2)), [], threshold=0.85)
    assert clusters == []


def test_singletons_preserved_below_threshold() -> None:
    names = ["Alice", "Bob", "Carol"]
    types = ["person"] * 3
    embs = np.array([_emb([1, 0]), _emb([0, 1]), _emb([-1, 0])])
    clusters = cluster_entities(names, embs, types, threshold=0.5)
    assert len(clusters) == 3
    assert all(len(c) == 1 for c in clusters)


# -- lexical containment guard (safety vs over-merging) --------------------

def test_lexical_substring_allows_merge() -> None:
    names = ["Sébastien Boutet", "Sébastien Jean Christophe Boutet"]
    types = ["person", "person"]
    embs = np.array([_emb([1, 0]), _emb([0.97, 0.05])])
    clusters = cluster_entities(names, embs, types, threshold=0.85)
    assert any(len(c) > 1 for c in clusters)


def test_case_variants_merge() -> None:
    names = ["NICE", "Nice"]
    types = ["location", "location"]
    embs = np.array([_emb([1, 0]), _emb([1, 0])])
    clusters = cluster_entities(names, embs, types, threshold=0.85)
    non_singleton = [c for c in clusters if len(c) > 1]
    assert len(non_singleton) == 1


def test_distinguishing_suffix_blocked_even_if_similar() -> None:
    """`Picture 1` and `Picture 2` look similar by embedding but are not the
    same entity — lexical-containment check must block the merge."""
    names = [
        "Plan de Prévention des Risques Miniers",
        "Plan de Prévention des Risques Technologiques",
        "Plan de Prévention des Risques Naturels",
    ]
    types = ["concept"] * 3
    # Very high cosine — would merge under embedding-only rules.
    embs = np.array([_emb([1, 0.01, 0]), _emb([0.99, 0.02, 0]), _emb([0.99, 0, 0.02])])
    clusters = cluster_entities(names, embs, types, threshold=0.5)
    assert all(len(c) == 1 for c in clusters), clusters


def test_ambiguous_prefix_does_not_bridge_distinct_variants() -> None:
    """Short prefix matches multiple distinguishing variants.

    `Plan Risques` is prefix of both `Plan Risques Miniers` and
    `Plan Risques Naturels`, but the two longer variants refer to
    different things. None must be merged — the prefix is ambiguous.
    """
    names = [
        "Plan Risques",
        "Plan Risques Miniers",
        "Plan Risques Naturels",
    ]
    types = ["concept"] * 3
    embs = np.array([_emb([1, 0, 0]), _emb([0.99, 0.01, 0]), _emb([0.99, 0, 0.01])])
    clusters = cluster_entities(names, embs, types, threshold=0.5)
    assert all(len(c) == 1 for c in clusters), clusters


def test_clique_of_three_merges() -> None:
    """If three variants are all pairwise equivalent, they should merge."""
    names = ["Sébastien Boutet", "Sébastien Jean Boutet", "Sébastien Jean Christophe Boutet"]
    types = ["person"] * 3
    # All orthogonal-ish embeddings — rely on lexical containment only.
    embs = np.array([_emb([1, 0.05, 0]), _emb([0.98, 0.1, 0]), _emb([0.97, 0.15, 0])])
    clusters = cluster_entities(names, embs, types, threshold=0.5)
    multi = [c for c in clusters if len(c) > 1]
    assert len(multi) == 1
    assert set(multi[0]) == set(names)


def test_fuzzy_mode_ignores_containment() -> None:
    names = ["Sibling A", "Sibling B"]
    types = ["concept", "concept"]
    embs = np.array([_emb([1, 0.01]), _emb([0.995, 0.02])])
    clusters = cluster_entities(
        names, embs, types, threshold=0.5,
        require_lexical_containment=False,
    )
    assert any(len(c) > 1 for c in clusters)
