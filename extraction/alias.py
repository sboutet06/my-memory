"""Alias resolution — progressive entity deduplication via embeddings.

Same real-world entity often arrives under multiple surface forms:
`Sébastien Boutet`, `Sebastien Jean Christophe Boutet`, `SEBASTIEN BOUTET`.
This module clusters entity names by embedding similarity, respecting
entity-type boundaries, and returns merge groups for downstream
consumers to apply.

Pure logic only — no graph I/O, no network. Domain-agnostic: clusterable
types are provided by the caller.
"""
from __future__ import annotations

import unicodedata
from typing import Iterable

import numpy as np

# Types for which name-similarity merging makes sense. Literal-value
# types (date, amount, identifier) must NOT be merged — "3370€" and
# "3 370 €" look similar but a graph that merges invoices-by-amount
# destroys real data.
DEFAULT_CLUSTERABLE_TYPES: frozenset[str] = frozenset(
    {"person", "organization", "location", "concept", "document"}
)

# Default cosine threshold. Conservative — prefers splitting to bad merges.
DEFAULT_THRESHOLD = 0.85


def normalize_name(s: str) -> str:
    """Casefold + strip accents + collapse whitespace."""
    if not s:
        return ""
    # NFKD decomposes accented chars so we can strip the combining marks.
    decomposed = unicodedata.normalize("NFKD", s)
    ascii_only = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(ascii_only.casefold().split())


def pick_canonical(cluster: list[str]) -> str:
    """Longest name wins (most information). Alphabetical tiebreak."""
    return max(cluster, key=lambda n: (len(n), -ord(n[:1] or "\uffff")))


# Union-find helpers -------------------------------------------------------

class _UF:
    __slots__ = ("parent",)

    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


# Public clustering --------------------------------------------------------

def _is_word_subsequence(short: list[str], long: list[str]) -> bool:
    """All `short` tokens appear in `long` in order (not necessarily contiguous)."""
    i = 0
    for w in long:
        if i < len(short) and w == short[i]:
            i += 1
    return i == len(short)


def _lexical_equivalent(a: str, b: str) -> bool:
    """True if normalized forms are equal, or one's tokens are a subsequence
    of the other's.

    Catches safe cases:
      - casing/accent variants: `NICE` / `Nice`
      - expansions: `Sébastien Boutet` / `Sébastien Jean Christophe Boutet`
      - formatting additions: `Véhicule de remplacement +` / without `+`

    Rejects distinguishing-suffix cases:
      - `Picture 1` / `Picture 2` — different token at a position
      - `Plan … Miniers` / `Plan … Technologiques` — different tail token
      - `Salaries - Conjoint` / `Salaries - Vous` — different tail token
    """
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    ta, tb = na.split(), nb.split()
    short, long = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return _is_word_subsequence(short, long)


def cluster_entities(
    names: list[str],
    embeddings: np.ndarray,
    types: list[str],
    *,
    threshold: float = DEFAULT_THRESHOLD,
    clusterable_types: Iterable[str] = DEFAULT_CLUSTERABLE_TYPES,
    require_lexical_containment: bool = True,
    ambiguous_out: list[list[str]] | None = None,
) -> list[list[str]]:
    """Group `names` into clusters of likely-same-entity.

    Rules (all must hold for a pair to merge):
    - Same entity type.
    - Type is in `clusterable_types`.
    - Pairwise cosine ≥ `threshold` (noise filter).
    - If `require_lexical_containment` (default True), the names must
      also be normalized-equal or one must be a substring of the other.
      This is the safety valve: pure embedding similarity over-merges
      (semantically-distinguishing suffixes read as similar). Set False
      for a fuzzier, user-reviewed pass.

    Returns clusters in insertion order; singletons included.

    If `ambiguous_out` is given, it is populated with the list of
    ambiguous-neighbour groups (each a list of surface names that the
    algorithm found mutually similar but which did not form a clique,
    so they were dropped from any merge). Use to surface these as
    human review candidates.
    """
    n = len(names)
    if n == 0:
        return []
    assert embeddings.shape[0] == n, "embeddings and names length mismatch"
    assert len(types) == n, "types and names length mismatch"

    allowed = set(clusterable_types)
    uf = _UF(n)

    by_type: dict[str, list[int]] = {}
    for i, t in enumerate(types):
        if t in allowed:
            by_type.setdefault(t, []).append(i)

    for indices in by_type.values():
        if len(indices) < 2:
            continue
        sub = embeddings[indices]
        sims = sub @ sub.T

        def _matches(ai: int, bi: int) -> bool:
            if sims[ai, bi] < threshold:
                return False
            if require_lexical_containment and not _lexical_equivalent(
                names[indices[ai]], names[indices[bi]]
            ):
                return False
            return True

        # Adjacency among local indices.
        neighbors: dict[int, set[int]] = {}
        for ai in range(len(indices)):
            neighbors[ai] = {
                bi for bi in range(len(indices)) if bi != ai and _matches(ai, bi)
            }

        # A node is "ambiguous" if its matches aren't a clique among themselves:
        # it bridges >1 distinct real entities (e.g. short prefix matching both
        # `Plan … Miniers` and `Plan … Technologiques`). Drop from any merge.
        ambiguous: set[int] = set()
        for ai, neigh in neighbors.items():
            neigh_list = sorted(neigh)
            for x in range(len(neigh_list)):
                if ai in ambiguous:
                    break
                for y in range(x + 1, len(neigh_list)):
                    if not _matches(neigh_list[x], neigh_list[y]):
                        ambiguous.add(ai)
                        break

        for ai in range(len(indices)):
            if ai in ambiguous:
                continue
            for bi in neighbors[ai]:
                if bi in ambiguous or bi <= ai:
                    continue
                uf.union(indices[ai], indices[bi])

        if ambiguous_out is not None and ambiguous:
            # For each ambiguous node, record the group {itself ∪ its neighbors},
            # deduplicated across ambiguous seeds that share a neighbourhood.
            seen_groups: set[tuple[str, ...]] = set()
            for ai in ambiguous:
                group_idxs = sorted({ai} | neighbors[ai])
                group_names = tuple(sorted(names[indices[gi]] for gi in group_idxs))
                if group_names in seen_groups:
                    continue
                seen_groups.add(group_names)
                ambiguous_out.append(list(group_names))

    components: dict[int, list[str]] = {}
    seen_roots: list[int] = []
    for i, name in enumerate(names):
        root = uf.find(i)
        if root not in components:
            components[root] = []
            seen_roots.append(root)
        components[root].append(name)
    return [components[r] for r in seen_roots]
