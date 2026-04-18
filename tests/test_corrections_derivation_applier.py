"""Applier planner: graph + corrections → Plan."""
from __future__ import annotations

from corrections.derivation_applier import (
    MergeOp,
    Plan,
    TypeChange,
    build_plan,
)
from corrections.derivation_schemas import (
    AliasCorrection,
    EntityTypeBucket,
    EntityTypeEntry,
)
from corrections.schemas import (
    Confidence,
    Doubt,
    SuggestedAction,
)


def _doubt() -> Doubt:
    return Doubt(
        field="merge_decision", inferred_value="split",
        confidence=Confidence.LOW, rationale="r",
        suggested_action=SuggestedAction.REVIEW,
    )


class TestTypeChanges:
    def test_only_changes_for_actual_differences(self) -> None:
        graph = {
            "Gabriel": {"entity_type": "concept"},
            "Alice": {"entity_type": "person"},
        }
        buckets = [EntityTypeBucket(
            bucket="concept_fallback",
            entries=[
                EntityTypeEntry(name="Gabriel", inferred_type="concept",
                                override_type="person"),
                # No-op: override equals current type.
                EntityTypeEntry(name="Alice", inferred_type="person",
                                override_type="person"),
            ],
        )]
        plan = build_plan(graph, buckets=buckets, aliases=[])
        assert plan.type_changes == [
            TypeChange(name="Gabriel", old_type="concept", new_type="person"),
        ]

    def test_skips_override_for_missing_node(self) -> None:
        # User override targets a name that is no longer in the graph.
        graph = {"Alice": {"entity_type": "person"}}
        buckets = [EntityTypeBucket(
            bucket="b",
            entries=[EntityTypeEntry(name="Ghost", inferred_type="concept",
                                     override_type="person")],
        )]
        plan = build_plan(graph, buckets=buckets, aliases=[])
        assert plan.type_changes == []
        assert "Ghost" in plan.warnings[0]

    def test_no_override_no_change(self) -> None:
        graph = {"X": {"entity_type": "concept"}}
        buckets = [EntityTypeBucket(
            bucket="b",
            entries=[EntityTypeEntry(name="X", inferred_type="concept")],
        )]
        plan = build_plan(graph, buckets=buckets, aliases=[])
        assert plan.type_changes == []


class TestAliasActions:
    def _alias(self, action=None, canonical=None, split_groups=None,
              members=("A", "B")) -> AliasCorrection:
        overrides: dict = {}
        if action is not None:
            overrides["action"] = action
        if canonical is not None:
            overrides["canonical"] = canonical
        if split_groups is not None:
            overrides["split_groups"] = split_groups
        return AliasCorrection(
            cluster="c", members=list(members), doubts=[_doubt()],
            overrides=overrides or {"action": None},
        )

    def test_accept_no_op(self) -> None:
        plan = build_plan(
            graph={"A": {"entity_type": "person"}, "B": {"entity_type": "person"}},
            buckets=[], aliases=[self._alias(action=None)],
        )
        assert plan.merge_ops == []

    def test_veto_is_no_op(self) -> None:
        plan = build_plan(
            graph={"A": {"entity_type": "person"}, "B": {"entity_type": "person"}},
            buckets=[], aliases=[self._alias(action="veto")],
        )
        assert plan.merge_ops == []

    def test_merge_with_explicit_canonical(self) -> None:
        plan = build_plan(
            graph={"A": {"entity_type": "person"},
                   "Alice": {"entity_type": "person"},
                   "ALICE": {"entity_type": "person"}},
            buckets=[],
            aliases=[self._alias(
                action="merge", canonical="Alice",
                members=["A", "Alice", "ALICE"],
            )],
        )
        assert plan.merge_ops == [
            MergeOp(canonical="Alice", sources=("A", "ALICE")),
        ]

    def test_merge_picks_canonical_when_unspecified(self) -> None:
        # Longest name wins (pick_canonical semantics).
        plan = build_plan(
            graph={"Sébastien Boutet": {"entity_type": "person"},
                   "S. Boutet": {"entity_type": "person"}},
            buckets=[],
            aliases=[self._alias(
                action="merge", members=["Sébastien Boutet", "S. Boutet"],
            )],
        )
        assert len(plan.merge_ops) == 1
        op = plan.merge_ops[0]
        assert op.canonical == "Sébastien Boutet"
        assert op.sources == ("S. Boutet",)

    def test_split_emits_one_op_per_group(self) -> None:
        plan = build_plan(
            graph={n: {"entity_type": "location"}
                   for n in ["Plan Miniers", "Plan M2", "Plan Nat", "Plan N2"]},
            buckets=[],
            aliases=[self._alias(
                action="split",
                split_groups=[["Plan Miniers", "Plan M2"],
                              ["Plan Nat", "Plan N2"]],
                members=["Plan Miniers", "Plan M2", "Plan Nat", "Plan N2"],
            )],
        )
        assert len(plan.merge_ops) == 2
        canonicals = sorted(op.canonical for op in plan.merge_ops)
        assert canonicals == ["Plan Miniers", "Plan Nat"]  # longest-per-group

    def test_merge_skips_missing_members(self) -> None:
        plan = build_plan(
            graph={"A": {"entity_type": "person"}},  # B gone
            buckets=[],
            aliases=[self._alias(action="merge", members=["A", "B"])],
        )
        # Single surviving member can't merge; op dropped with warning.
        assert plan.merge_ops == []
        assert any("B" in w for w in plan.warnings)


class TestIdempotency:
    def test_same_inputs_same_plan(self) -> None:
        graph = {"Gabriel": {"entity_type": "concept"}}
        buckets = [EntityTypeBucket(
            bucket="b",
            entries=[EntityTypeEntry(name="Gabriel", inferred_type="concept",
                                     override_type="person")],
        )]
        p1 = build_plan(graph, buckets=buckets, aliases=[])
        p2 = build_plan(graph, buckets=buckets, aliases=[])
        assert p1 == p2

    def test_post_type_change_same_plan_is_no_op(self) -> None:
        """Running the plan once should make re-planning produce nothing."""
        graph = {"Gabriel": {"entity_type": "concept"}}
        buckets = [EntityTypeBucket(
            bucket="b",
            entries=[EntityTypeEntry(name="Gabriel", inferred_type="concept",
                                     override_type="person")],
        )]
        # simulate having applied the change
        graph["Gabriel"]["entity_type"] = "person"
        p = build_plan(graph, buckets=buckets, aliases=[])
        assert p.type_changes == []
